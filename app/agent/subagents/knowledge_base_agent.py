"""
知识库子智能体配置模块

将 app/prompt/prompts.yml 中的 ragflow 配置与本地知识库工具组装成
DeepAgents 可识别的字典式子智能体。主智能体后续会根据 description
决定是否把企业内部非结构化文档查询任务分派给它。

【当前实现】本地轻量 RAG（python 侧解析 + bge-m3 嵌入 + numpy 检索），
不依赖 RAGFlow 服务，工具来自 app/tools/local_kb_tools.py。

【可切回】RAGFlow 版工具仍保留在 app/tools/ragflow_tools.py，
下方被注释的 import 与 tools 声明可直接恢复。切换时需同时恢复提示词中
对 get_assistant_list / create_ask_delete 的描述。
"""

from app.agent.prompts import sub_agents_content

# ---------------------------------------------------------------------------
# RAGFlow 版本（已停用，保留以便切回）
# ---------------------------------------------------------------------------
# from app.tools.ragflow_tools import create_ask_delete, get_assistant_list

# ---------------------------------------------------------------------------
# 本地轻量 RAG 版本（当前启用）
# ---------------------------------------------------------------------------
from app.tools.local_kb_tools import ask_knowledge_base, list_knowledge_bases

# 知识库子智能体处理内部非结构化文档，与网络搜索助手、数据库查询助手形成互补
# 它遵循"先查知识库分类 -> 再检索相关片段"的工作顺序
# tools 列表声明该子智能体可以发现可用知识库，并按问题检索证据片段
knowledge_base_agent = {
    "name": sub_agents_content["ragflow"]["name"],
    "description": sub_agents_content["ragflow"]["description"],
    "system_prompt": sub_agents_content["ragflow"]["system_prompt"],
    # 本地 RAG：先列分类，再检索
    "tools": [list_knowledge_bases, ask_knowledge_base],
    # RAGFlow：先列助手，再提问（已停用，保留以便切回）
    # "tools": [get_assistant_list, create_ask_delete],
}
