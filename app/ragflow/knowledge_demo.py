"""
RAGFlow 知识库初始化工具

通过 RAGFlow SDK 创建 Dataset、上传本地目录中的参考文档，用于在切回
RAGFlow 方案时快速准备知识库数据。本模块不参与 Agent 运行时，
由运维人员在部署阶段手动执行。

当前项目默认使用本地轻量 RAG（app/knowledge/local_kb.py），
只有在 .env 配好 RAGFLOW_API_URL / RAGFLOW_API_KEY 并切回 RAGFlow 工具后
才需要运行本脚本。

用法：
    python -m app.ragflow.knowledge_demo --name 金融行业 --desc "银行与资管研报" \\
        --dir docs/knowledge_base/金融行业
"""

import argparse
import os
from pathlib import Path

from ragflow_sdk import RAGFlow

from app.ragflow.rag_config import _load_ragflow_env

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 支持上传到 RAGFlow 的文档后缀
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".doc", ".md", ".txt", ".xlsx", ".csv"}


def _client() -> RAGFlow:
    """按 .env 中的地址和密钥构造 RAGFlow 客户端。"""
    api_key, base_url = _load_ragflow_env()
    if not api_key or not base_url:
        raise RuntimeError(
            "未配置 RAGFLOW_API_URL / RAGFLOW_API_KEY，无法连接 RAGFlow 服务"
        )
    return RAGFlow(api_key=api_key, base_url=base_url)


def create_knowledge_base(knowledge_base_name: str, description: str) -> str:
    """
    创建 RAGFlow 知识库（Dataset），返回其 id。

    :param knowledge_base_name: 知识库名称，需与后续聊天助手绑定名称对应
    :param description: 知识库描述，Agent 依据描述判断该问哪个助手
    """
    client = _client()
    dataset = client.create_dataset(
        name=knowledge_base_name,
        description=description,
        embedding_model="text-embedding-v3@Tongyi-Qianwen",
    )
    print(f"知识库创建成功：{dataset.name}（{dataset.id}）")
    return dataset.id


def upload_documents(kb_id: str, file_paths: list[str]) -> None:
    """
    向指定知识库批量上传本地文档。

    上传只完成文件入库，还需要在 RAGFlow 侧触发解析与向量化，
    否则文档尚未切片，聊天助手检索不到内容。

    :param kb_id: 知识库 id（Dataset id）
    :param file_paths: 本地文件路径列表
    """
    client = _client()
    datasets = client.list_datasets(id=kb_id, page=1, page_size=10)
    if not datasets:
        raise ValueError(f"知识库不存在：{kb_id}")
    dataset = datasets[0]

    document_list = []
    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        with open(file_path, "rb") as handle:
            document_list.append(
                {"display_name": file_name, "name": file_name, "blob": handle.read()}
            )

    if not document_list:
        print("没有匹配到可上传的文档")
        return

    dataset.upload_documents(document_list)
    print(f"已上传 {len(document_list)} 个文档到知识库 {dataset.name}")


def collect_documents(target_dir: str) -> list[str]:
    """递归收集目录下所有受支持的文档。"""
    root = PROJECT_ROOT / target_dir
    if not root.is_dir():
        raise NotADirectoryError(f"目录不存在：{root}")
    return [
        str(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 RAGFlow 知识库并上传文档")
    parser.add_argument("--name", required=True, help="知识库名称")
    parser.add_argument("--desc", default="", help="知识库描述")
    parser.add_argument("--dir", default="", help="待上传文档所在目录（相对项目根）")
    args = parser.parse_args()

    kb_id = create_knowledge_base(args.name, args.desc)
    if args.dir:
        upload_documents(kb_id, collect_documents(args.dir))


if __name__ == "__main__":
    main()
