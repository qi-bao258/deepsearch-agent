"""
本地知识库工具模块（替代 RAGFlow 版工具）

封装两个给知识库子智能体使用的 LangChain 工具：
list_knowledge_bases 用于发现有哪些知识库分类、包含哪些文档，
ask_knowledge_base   用于按问题检索相关片段并组装成可直接阅读的证据文本。

与 RAGFlow 版本的对应关系：
  RAGFlow 版 get_assistant_list -> 本文件 list_knowledge_bases
  RAGFlow 版 create_ask_delete  -> 本文件 ask_knowledge_base
工具语义保持一致：只返回检索到的原始资料与出处，不做最终结论，交由主智能体汇总。
"""

from __future__ import annotations

import os

from langchain_core.tools import tool

from app.api.monitor import monitor
from app.knowledge import local_kb


def _ensure_index() -> dict | None:
    """
    确保索引可用；缺失或过期时自动构建

    :return: 新建索引时返回统计信息，已存在则返回 None
    """
    if local_kb.index_exists():
        return None

    def _progress(step: int, total: int) -> None:
        # 每 10% 上报一次，避免前端事件流被刷屏
        if step == total or step % max(total // 10, 1) == 0:
            monitor.report_tool(
                tool_name=f"知识库索引构建中：{step}/{total} 批",
                args={"progress": round(step / total, 2)},
            )

    return local_kb.rebuild_index(progress=_progress)


@tool
def list_knowledge_bases() -> str:
    """
    查询本地知识库有哪些分类和文档，以及每个分类的片段数量

    作用：让模型先了解"内部私有资料里都有什么"，再决定是否检索、检索哪个分类。
    调用 ask_knowledge_base 之前，应先调用本工具确认可用分类与文档范围。
    :return: 分类名称、片段数、文档清单；知识库为空时返回中文提示
    """
    monitor.report_tool(tool_name="知识库分类与文档列表查询工具：list_knowledge_bases")

    try:
        _ensure_index()
        categories = local_kb.list_categories()
        if not categories:
            return "本地知识库中没有任何文档，请把 PDF/Word/Excel/Markdown 放入 docs/knowledge_base 后重试"

        # 汇总每个分类下的文档名，便于模型判断题能否交由该分类回答
        _, chunks = local_kb.load_index()
        docs_by_category: dict[str, list[str]] = {}
        for chunk in chunks:
            names = docs_by_category.setdefault(chunk.category, [])
            if chunk.source not in names:
                names.append(chunk.source)

        lines = ["本地知识库可用分类如下："]
        for category, count in sorted(categories.items(), key=lambda x: -x[1]):
            docs = "、".join(docs_by_category.get(category, []))
            lines.append(f"- 分类：{category}；片段数：{count}；包含文档：{docs}")
        return "\n".join(lines)
    except Exception as e:
        return f"查询知识库信息异常，无可用知识库，异常信息：{str(e)}"


@tool
def ask_knowledge_base(question: str, category: str = "", top_k: int = 0) -> str:
    """
    在本地知识库中检索与问题相关的原文片段，并返回带出处的证据文本

    注意：调用此工具之前，必须先调用 list_knowledge_bases，明确可用分类与文档范围。
    本工具只做检索与证据整理，不做最终结论，结论由主智能体基于返回片段汇总。
    :param question: 本次检索的问题，应当围绕用户原始需求
    :param category: 可选，限定在某个分类内检索；留空表示全库检索
    :param top_k: 返回片段数；留空或 0 时使用 .env 的 KB_TOP_K（默认 5），上限 20
    :return: 按相关度排序的片段及其来源页码；异常时返回中文错误提示
    """
    monitor.report_tool(
        tool_name="知识库检索工具：ask_knowledge_base",
        args={"question": question, "category": category, "top_k": top_k},
    )

    try:
        _ensure_index()

        # 未显式指定时回落到 .env 的 KB_TOP_K，避免配置项写了却不生效
        if not top_k:
            top_k = int(os.getenv("KB_TOP_K", "5"))

        # 分类名做一次宽松匹配，容忍模型传入「金融行业」/「金融」这类差异
        resolved_category = ""
        categories = local_kb.list_categories()
        if category:
            matched = [c for c in categories if category in c or c in category]
            resolved_category = matched[0] if matched else category

        results = local_kb.search(question, top_k=top_k, category=resolved_category or None)
        if not results:
            scope = f"分类「{resolved_category}」中" if resolved_category else "知识库中"
            return f"{scope}没有检索到与问题相关的内容，请调整问题表述或确认资料是否已导入"

        blocks = [f"问题：{question}"]
        for index, (score, chunk) in enumerate(results, start=1):
            page_info = f" 第{chunk.page}页" if chunk.page else ""
            blocks.append(
                f"\n[片段{index}] 来源：{chunk.category}/{chunk.source}{page_info}；相关度：{score:.3f}\n{chunk.text}"
            )
        return "\n".join(blocks)
    except Exception as e:
        return f"知识库检索失败，错误原因：{str(e)}"


if __name__ == "__main__":
    # 本地调试入口：直接运行可验证索引构建与检索是否正常
    print(list_knowledge_bases.invoke({}))
    print("\n" + "=" * 60 + "\n")
    print(
        ask_knowledge_base.invoke(
            {
                "question": "如果我是一个电商平台运营负责人，应该怎样制定 2026 年 AI 应用路线图？",
                "category": "电商行业",
                "top_k": 3,
            }
        )
    )
