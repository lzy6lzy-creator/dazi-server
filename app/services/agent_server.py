from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentModelConfig:
    provider: str
    model: str
    base_url: str
    api_key: str


def _infer_provider(base_url: str, model: str) -> str:
    text = f"{base_url} {model}".lower()
    if "deepseek" in text:
        return "deepseek"
    return "kimi"


def _fallback_config(*, provider: str, model: str, base_url: str, api_key: str) -> AgentModelConfig:
    effective_model = model or settings.LLM_MODEL
    effective_base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
    return AgentModelConfig(
        provider=provider or _infer_provider(effective_base_url, effective_model),
        model=effective_model,
        base_url=effective_base_url,
        api_key=api_key or settings.LLM_API_KEY,
    )


def load_conversation_config() -> AgentModelConfig:
    return _fallback_config(
        provider=settings.AGENT_MODEL_PROVIDER,
        model=settings.AGENT_MODEL,
        base_url=settings.AGENT_BASE_URL,
        api_key=settings.AGENT_API_KEY,
    )


def load_draft_config() -> AgentModelConfig:
    if any([
        settings.AGENT_DRAFT_MODEL_PROVIDER,
        settings.AGENT_DRAFT_MODEL,
        settings.AGENT_DRAFT_BASE_URL,
        settings.AGENT_DRAFT_API_KEY,
    ]):
        return _fallback_config(
            provider=settings.AGENT_DRAFT_MODEL_PROVIDER,
            model=settings.AGENT_DRAFT_MODEL,
            base_url=settings.AGENT_DRAFT_BASE_URL,
            api_key=settings.AGENT_DRAFT_API_KEY,
        )
    return load_conversation_config()


class AgentServer:
    def __init__(
        self,
        *,
        conversation_config: AgentModelConfig | None = None,
        draft_config: AgentModelConfig | None = None,
    ):
        self.conversation_config = conversation_config or load_conversation_config()
        self.draft_config = draft_config or load_draft_config()
        self._client: httpx.AsyncClient | None = None

    def start(self) -> None:
        if self._client is not None and not self._client.is_closed:
            return
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"Content-Type": "application/json"},
        )

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self.start()
        assert self._client is not None
        return self._client

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> Any:
        text = ""
        async for piece in self.stream_chat(
            messages,
            purpose=purpose,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            text += piece
        return self.extract_json(text)

    @staticmethod
    def extract_json(text: str) -> Any:
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue

        logger.warning("Failed to extract JSON from agent server output: %s", text[:200])
        return None

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        config = self.draft_config if purpose == "draft" else self.conversation_config
        payload = self._payload(config, messages, temperature=temperature, max_tokens=max_tokens)
        async with self.client.stream(
            "POST",
            f"{config.base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                piece = self._delta_content(chunk)
                if piece:
                    yield piece

    def _payload(
        self,
        config: AgentModelConfig,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        actual_temperature = 0.6 if config.provider == "kimi" and "k2" in config.model else temperature
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": actual_temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if config.provider in {"kimi", "deepseek"}:
            payload["thinking"] = {"type": "disabled"}
        return payload

    @staticmethod
    def _delta_content(chunk: dict[str, Any]) -> str:
        choices = chunk.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        return content if isinstance(content, str) else ""


agent_server = AgentServer()
