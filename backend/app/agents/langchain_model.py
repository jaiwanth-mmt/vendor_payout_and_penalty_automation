"""LangChain chat model factory from existing Azure OpenAI env vars."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI


def azure_chat_model_from_env() -> BaseChatModel | None:
    """Build a ChatOpenAI client pointed at Azure chat-completions URL, or None if unset."""
    api_url = os.getenv("AZURE_OPENAI_CHAT_COMPLETIONS_URL", "").strip()
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    if not api_url or not api_key:
        return None
    return build_azure_chat_model(api_url=api_url, api_key=api_key)


def build_azure_chat_model(*, api_url: str, api_key: str, **kwargs: Any) -> ChatOpenAI:
    """
    Construct ChatOpenAI for an Azure chat-completions endpoint.

    Uses the existing AZURE_OPENAI_CHAT_COMPLETIONS_URL (full URL) + api-key header —
    no new env vars.
    """
    parsed = urlparse(api_url)
    # ChatOpenAI appends /chat/completions; strip that suffix if present so base_url is the API root.
    path = parsed.path.rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    base_url = f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")
    model_name = kwargs.pop("model", None) or os.getenv("AZURE_OPENAI_DEPLOYMENT", "azure-openai")
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        default_headers={"api-key": api_key},
        **kwargs,
    )


@lru_cache(maxsize=1)
def cached_azure_chat_model() -> BaseChatModel | None:
    return azure_chat_model_from_env()
