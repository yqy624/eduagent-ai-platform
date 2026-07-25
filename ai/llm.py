"""LLM 配置与调用 — 支持 Ollama、OpenAI、通义千问、Claude"""
import os
from typing import Optional
from langchain_openai import ChatOpenAI
from app.config import settings


def get_llm(temperature: float = 0.3, model_name: Optional[str] = None):
    """获取 LLM 实例。优先 Ollama，其次 API Key 配置。"""
    ollama_model = settings.ollama_model or os.getenv("OLLAMA_MODEL", "")
    if ollama_model:
        return ChatOpenAI(
            model=model_name or ollama_model,
            temperature=temperature,
            api_key="ollama",
            base_url=f"{settings.ollama_base_url}/v1",
        )
    if settings.openai_api_key:
        return ChatOpenAI(
            model=model_name or settings.openai_model or "gpt-4o",
            temperature=temperature,
            api_key=settings.openai_api_key,
        )
    if settings.dashscope_api_key:
        from langchain_dashscope import ChatDashScope
        return ChatDashScope(
            model=model_name or settings.dashscope_model or "qwen-max",
            temperature=temperature,
            api_key=settings.dashscope_api_key,
        )
    if settings.anthropic_api_key:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name or settings.anthropic_model or "claude-sonnet-4",
            temperature=temperature,
            api_key=settings.anthropic_api_key,
        )
    raise ValueError("未配置任何 LLM（请设置 OLLAMA_MODEL 或 API Key）")


def get_embeddings():
    """获取 Embedding 模型。返回 None 时使用基于 LLM 的检索替代。"""
    return None
