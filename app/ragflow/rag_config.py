"""
【已停用】RAGFlow 连接配置加载模块（保留以便随时切回）

集中读取 RAGFlow SDK 需要的 API Key 和服务地址，供知识库初始化脚本与
LangChain 工具共用。这样后续如果 .env 字段或读取规则调整，只需要改这一处。

当前项目已切换为本地轻量 RAG，本模块不再被任何业务代码引用。
"""

import os
from typing import Optional, Tuple

from dotenv import find_dotenv, load_dotenv


def _load_ragflow_env() -> Tuple[Optional[str], Optional[str]]:
    """
    加载 RAGFlow 环境变量

    使用 python-dotenv 自动向上查找 .env，保持和项目其他配置加载方式一致。
    :return: (api_key, base_url)，缺失配置时对应位置返回 None
    """
    load_dotenv(find_dotenv())

    # RAGFlow SDK 初始化只需要这两个核心字段：认证 API Key 和服务基础地址
    api_key = os.getenv("RAGFLOW_API_KEY")
    base_url = os.getenv("RAGFLOW_API_URL")
    return api_key, base_url
