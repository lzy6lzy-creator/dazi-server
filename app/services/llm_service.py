from __future__ import annotations

"""
LLM Service - 调用月之暗面 Kimi API

优化：
- httpx 连接池复用（避免每次请求新建连接）
- 自动重试（指数退避）
- JSON 结构化输出提取
- 超时与错误处理
"""
import json
import re
import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """LLM 客户端，httpx 连接池由 lifespan 管理"""

    _client: httpx.AsyncClient | None = None

    def __init__(self):
        self.base_url = settings.LLM_BASE_URL
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self._semaphore: asyncio.Semaphore | None = None
        self._rate_lock: asyncio.Lock | None = None
        self._last_request_at = 0.0

    def start(self):
        """初始化 httpx 客户端，应在 lifespan 启动阶段调用"""
        if self._client is not None and not self._client.is_closed:
            return
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        logger.info("LLM httpx client initialized.")

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(max(1, settings.LLM_MAX_CONCURRENT_REQUESTS))
        return self._semaphore

    def _get_rate_lock(self) -> asyncio.Lock:
        if self._rate_lock is None:
            self._rate_lock = asyncio.Lock()
        return self._rate_lock

    async def _throttle(self):
        min_interval = max(0.0, settings.LLM_MIN_INTERVAL_SECONDS)
        if min_interval <= 0:
            return
        async with self._get_rate_lock():
            now = time.monotonic()
            wait = self._last_request_at + min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    @property
    def client(self) -> httpx.AsyncClient:
        """获取 httpx 客户端，必须先调用 start()"""
        if self._client is None or self._client.is_closed:
            raise RuntimeError("LLM client not started. Call llm_service.start() in lifespan.")
        return self._client

    async def close(self):
        """关闭客户端连接池，应在 lifespan 关闭阶段调用"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("LLM httpx client closed.")
        self._client = None

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        retries: int | None = None,
    ) -> str:
        """调用 LLM 获取回复，带自动重试"""
        max_retries = settings.LLM_RETRIES if retries is None else retries

        # kimi-k2 系列禁用思考后 temperature 固定为 0.6
        actual_temp = temperature
        if "k2" in self.model:
            actual_temp = 0.6

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": actual_temp,
            "max_tokens": max_tokens,
        }

        # kimi-k2 系列默认启用思考，禁用以直接返回 content
        if "k2" in self.model:
            payload["thinking"] = {"type": "disabled"}

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                async with self._get_semaphore():
                    await self._throttle()
                    response = await self.client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                    )
                response.raise_for_status()
                data = response.json()

                # 处理 kimi 推理模型：优先取 content，跳过 reasoning_content
                choice = data["choices"][0]["message"]
                content = choice.get("content") or ""

                if not content and choice.get("reasoning_content"):
                    content = "我正在思考中，请稍等..."

                return content

            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code
                # 429 限流 或 5xx 服务端错误才重试
                if status == 429 or status >= 500:
                    wait = min(60.0, max(settings.LLM_MIN_INTERVAL_SECONDS, (2 ** attempt) + 2.0))
                    logger.warning(f"LLM API {status}, retry {attempt+1}/{max_retries} after {wait}s")
                    await asyncio.sleep(wait)
                    continue
                # 4xx 其他错误不重试
                logger.error(f"LLM API error {status}: {e.response.text}")
                logger.error(f"LLM request payload: model={payload.get('model')}, temperature={payload.get('temperature')}, thinking={payload.get('thinking')}")
                raise

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                last_error = e
                wait = min(60.0, max(settings.LLM_MIN_INTERVAL_SECONDS, (2 ** attempt) + 2.0))
                logger.warning(f"LLM network error: {e}, retry {attempt+1}/{max_retries} after {wait}s")
                await asyncio.sleep(wait)
                continue

        raise last_error or RuntimeError("LLM call failed after retries")

    async def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> Any:
        """调用 LLM 并解析 JSON 输出"""
        raw = await self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return self._extract_json(raw)

    @staticmethod
    def _extract_json(text: str) -> Any:
        """从 LLM 输出中提取 JSON，兼容 markdown 代码块"""
        # 尝试提取 ```json ... ``` 代码块
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        # 尝试解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 兜底：找第一个 { 或 [ 开头的片段
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue

        logger.warning(f"Failed to extract JSON from LLM output: {text[:200]}")
        return None


# 全局单例
llm_service = LLMService()
