"""
本地轻量知识库核心模块（RAGFlow 的本地替代实现）

职责与 RAGFlow 对齐：把企业内部非结构化文档切块、向量化、按问题检索出相关片段。
不依赖任何外部服务进程，只使用项目已有依赖（pypdf / python-docx / openpyxl / numpy）
加上一个 OpenAI 兼容的 Embedding 接口（默认 BAAI/bge-m3）。

设计要点：
1. 切块、相似度计算都是纯函数，便于单测和结果复现；
2. 索引落盘为 docs/knowledge_base/.kb_index/ 下的 npz + json，避免每次任务重新嵌入；
3. 文档指纹（路径 + 大小 + 修改时间）参与索引校验，文档增删改后自动重建；
4. 检索只返回原文片段与来源，不生成结论，最终汇总交给主智能体，语义与 RAGFlow 工具一致。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
from dotenv import find_dotenv, load_dotenv

# 与其他工具模块保持一致：从当前目录向上查找 .env，保证脚本与 Web 服务都能拿到配置
load_dotenv(find_dotenv())

# 知识库根目录：默认指向项目自带示例文档 docs/knowledge_base
# 支持通过 .env 的 KB_ROOT 覆盖（可为相对路径，相对于项目根目录）
APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parent


def _resolve_kb_root() -> Path:
    """解析知识库目录：未配置时回落到 docs/knowledge_base"""
    raw = os.getenv("KB_ROOT", "").strip()
    if not raw:
        return PROJECT_ROOT / "docs" / "knowledge_base"
    candidate = Path(raw)
    if not candidate.is_absolute():
        # 相对路径优先按项目根目录解析，不存在时再按 app 目录解析
        project_relative = PROJECT_ROOT / candidate
        candidate = project_relative if project_relative.exists() else APP_ROOT / candidate
    return candidate


KB_ROOT = _resolve_kb_root()
INDEX_DIR = PROJECT_ROOT / "docs" / "knowledge_base" / ".kb_index"

# 切块参数：500 字/块、重叠 80 字，兼顾语义完整性与检索精度
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

# 支持解析的文档后缀；PDF 走 pypdf，Office 格式走对应库，纯文本直接读
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".csv"}

# 单个知识库最多参与检索的片段数上限，防止一次性塞爆模型上下文
MAX_TOP_K = 20


@dataclass
class Chunk:
    """一个可检索的文本片段"""

    text: str
    source: str  # 原始文件名
    category: str  # 一级目录名，例如「金融行业」
    page: int  # PDF 页码，非 PDF 记为 0


# ---------------------------------------------------------------------------
# 文档解析
# ---------------------------------------------------------------------------


def _read_pdf(path: Path) -> list[tuple[int, str]]:
    """按页读取 PDF，返回 [(页码, 文本)]；页码从 1 开始"""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((index, text))
    return pages


def _read_docx(path: Path) -> list[tuple[int, str]]:
    """读取 Word 文档，段落按顺序拼接，页码信息记为 0"""
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    # 表格内容也要纳入，否则研报里的数据表会整体丢失
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return [(0, "\n".join(parts))]


def _read_xlsx(path: Path) -> list[tuple[int, str]]:
    """读取 Excel，每个工作表转成 CSV 风格文本"""
    import openpyxl

    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    for sheet in workbook.worksheets:
        parts.append(f"# 工作表: {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                parts.append(" | ".join(cells))
    workbook.close()
    return [(0, "\n".join(parts))]


def _read_text(path: Path) -> list[tuple[int, str]]:
    """读取纯文本类文件，编码异常时用替换字符兜底，避免整份文档失败"""
    return [(0, path.read_text(encoding="utf-8", errors="replace"))]


def read_document(path: Path) -> list[tuple[int, str]]:
    """按后缀分派到对应解析器；不支持的类型返回空列表"""
    suffix = path.suffix.lower()
    readers = {
        ".pdf": _read_pdf,
        ".docx": _read_docx,
        ".xlsx": _read_xlsx,
        ".md": _read_text,
        ".txt": _read_text,
        ".csv": _read_text,
    }
    reader = readers.get(suffix)
    if reader is None:
        return []
    return reader(path)


# ---------------------------------------------------------------------------
# 切块
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """压缩多余空白，保证同一页文本切块结果稳定可复现"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    把长文本切成带重叠的片段

    纯函数：相同输入必然得到相同输出，便于索引复用与单元测试。
    overlap 必须小于 size，否则窗口无法前进会导致死循环。
    """
    if size <= 0:
        raise ValueError("size 必须为正整数")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap 必须满足 0 <= overlap < size")

    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    step = size - overlap
    while start < len(text):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append(piece)
        if start + size >= len(text):
            break
        start += step
    return chunks


def build_chunks() -> list[Chunk]:
    """遍历知识库目录，把所有文档解析并切块"""
    chunks: list[Chunk] = []
    if not KB_ROOT.exists():
        return chunks

    for path in sorted(KB_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        # 跳过索引目录本身与隐藏文件
        if INDEX_DIR in path.parents or path.name.startswith("."):
            continue

        category = path.relative_to(KB_ROOT).parts[0] if path.parent != KB_ROOT else "未分类"
        try:
            pages = read_document(path)
        except Exception as exc:  # 单份文档损坏不应阻断整库构建
            print(f"[LocalKB] 解析失败，已跳过 {path.name}: {exc}")
            continue

        for page_no, page_text in pages:
            for piece in split_text(page_text):
                chunks.append(
                    Chunk(text=piece, source=path.name, category=category, page=page_no)
                )
    return chunks


# ---------------------------------------------------------------------------
# 向量化（OpenAI 兼容 Embedding 接口）
# ---------------------------------------------------------------------------


class EmbeddingClient:
    """最小化的 OpenAI 兼容 Embedding 客户端"""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.base_url = (base_url or os.getenv("EMBEDDING_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("EMBEDDING_API_KEY") or ""
        self.model = model or os.getenv("EMBEDDING_MODEL") or ""
        self.batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))

    def validate(self) -> None:
        """配置缺失时尽早失败，避免构建到一半才发现没有 Key"""
        missing = [
            name
            for name, value in (
                ("EMBEDDING_BASE_URL", self.base_url),
                ("EMBEDDING_API_KEY", self.api_key),
                ("EMBEDDING_MODEL", self.model),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"缺失 Embedding 配置：{', '.join(missing)}，请在 .env 中补齐")

    def embed(self, texts: Iterable[str]) -> np.ndarray:
        """批量嵌入，返回 float32 矩阵，形状为 [文本数, 维度]"""
        import requests

        self.validate()
        items = list(texts)
        if not items:
            return np.zeros((0, 0), dtype="float32")

        vectors: list[list[float]] = []
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        for start in range(0, len(items), self.batch_size):
            batch = items[start : start + self.batch_size]
            response = requests.post(
                url,
                headers=headers,
                json={"model": self.model, "input": batch},
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            # 接口按 index 返回，正常与输入顺序一致；显式排序可防止服务端乱序
            rows = sorted(payload["data"], key=lambda x: x.get("index", 0))
            vectors.extend([row["embedding"] for row in rows])

        matrix = np.asarray(vectors, dtype="float32")
        return l2_normalize(matrix)


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """按行做 L2 归一化，归一化后点积即余弦相似度"""
    if matrix.size == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# ---------------------------------------------------------------------------
# 索引持久化
# ---------------------------------------------------------------------------


def _fingerprint() -> str:
    """对知识库目录做指纹，文档增删改后指纹变化即触发重建"""
    digest = hashlib.sha256()
    if not KB_ROOT.exists():
        return digest.hexdigest()
    for path in sorted(KB_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if INDEX_DIR in path.parents or path.name.startswith("."):
            continue
        stat = path.stat()
        digest.update(f"{path.relative_to(KB_ROOT)}|{stat.st_size}|{int(stat.st_mtime)}".encode())
    return digest.hexdigest()


def _meta_path() -> Path:
    return INDEX_DIR / "meta.json"


def _vectors_path() -> Path:
    return INDEX_DIR / "vectors.npy"


def index_exists() -> bool:
    """索引是否已构建且与当前文档一致"""
    if not (_meta_path().exists() and _vectors_path().exists()):
        return False
    try:
        meta = json.loads(_meta_path().read_text(encoding="utf-8"))
    except Exception:
        return False
    return meta.get("fingerprint") == _fingerprint() and meta.get("model") == os.getenv("EMBEDDING_MODEL")


def load_index() -> tuple[np.ndarray, list[Chunk]]:
    """读取已落盘索引；不存在或已过期时抛错，由调用方决定是否重建"""
    if not index_exists():
        raise FileNotFoundError("知识库索引不存在或已过期，请先执行 rebuild_index()")
    meta = json.loads(_meta_path().read_text(encoding="utf-8"))
    vectors = np.load(_vectors_path())
    chunks = [
        Chunk(text=c["text"], source=c["source"], category=c["category"], page=c["page"])
        for c in meta["chunks"]
    ]
    return vectors, chunks


def rebuild_index(progress: Optional[callable] = None) -> dict:
    """
    重建索引并落盘

    :param progress: 可选回调，签名 (当前页, 总页数)，用于前端展示构建进度
    :return: 统计信息，包含文档数、片段数、耗时
    """
    import time

    started = time.time()
    chunks = build_chunks()
    if not chunks:
        raise ValueError(f"知识库目录为空或无可解析文档：{KB_ROOT}")

    client = EmbeddingClient()
    client.validate()

    texts = [c.text for c in chunks]
    batch = max(client.batch_size, 1)
    vectors_list: list[np.ndarray] = []
    total_steps = (len(texts) + batch - 1) // batch
    for step, start in enumerate(range(0, len(texts), batch), start=1):
        vectors_list.append(client.embed(texts[start : start + batch]))
        if progress:
            progress(step, total_steps)

    vectors = np.vstack(vectors_list) if vectors_list else np.zeros((0, 0), dtype="float32")

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(_vectors_path(), vectors)
    meta = {
        "fingerprint": _fingerprint(),
        "model": os.getenv("EMBEDDING_MODEL"),
        "dim": int(vectors.shape[1]) if vectors.size else 0,
        "chunks": [
            {"text": c.text, "source": c.source, "category": c.category, "page": c.page}
            for c in chunks
        ],
    }
    _meta_path().write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    sources = {c.source for c in chunks}
    return {
        "documents": len(sources),
        "chunks": len(chunks),
        "dim": meta["dim"],
        "elapsed": round(time.time() - started, 2),
    }


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


def search(question: str, top_k: int = 5, category: Optional[str] = None) -> list[tuple[float, Chunk]]:
    """
    按问题检索最相关的片段

    :param question: 用户问题
    :param top_k: 返回片段数，超过 MAX_TOP_K 会被截断
    :param category: 可选，限定在某一个知识库分类内检索
    :return: [(相似度, 片段)]，按相似度降序
    """
    top_k = max(1, min(int(top_k), MAX_TOP_K))
    vectors, chunks = load_index()

    # 分类过滤在打分之后做，保证 numpy 计算仍是整矩阵一次点积
    query_vec = EmbeddingClient().embed([question])[0]
    scores = vectors @ query_vec

    order = np.argsort(-scores)
    results: list[tuple[float, Chunk]] = []
    for idx in order:
        chunk = chunks[idx]
        if category and chunk.category != category:
            continue
        results.append((float(scores[idx]), chunk))
        if len(results) >= top_k:
            break
    return results


def list_categories() -> dict[str, int]:
    """列出可用知识库分类及各自片段数，供子智能体先了解有哪些资料"""
    _, chunks = load_index()
    counter: dict[str, int] = {}
    for chunk in chunks:
        counter[chunk.category] = counter.get(chunk.category, 0) + 1
    return counter
