from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from app.domain.chat import ChatRequest, ChatResponse
from app.settings import Settings


class ChatClient(Protocol):
    async def complete(self, request: ChatRequest) -> ChatResponse: ...

    def stream(self, request: ChatRequest) -> AsyncIterator[str]: ...


class AiClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


SYSTEM_PROMPT = "\n".join(
    (
        "你是一名务实的中国旅行助手。",
        "支持中国境内任意目的地，并把用户提供的目的地和天数作为规划上下文。",
        "信息不足时明确说明假设，不要把猜测说成事实。",
        "不得编造坐标、地图 UID、路线几何、距离、时长、营业时间或实时可用性。",
        "用户询问精确地图事实时，说明当前尚未连接地图验证。",
    )
)


def build_provider_messages(request: ChatRequest) -> list[dict[str, str]]:
    context = [
        f"目的地：{request.destination}" if request.destination else "",
        f"旅行天数：{request.days} 天" if request.days else "",
    ]
    context = [item for item in context if item]
    context_text = "\n".join(context)
    user_content = (
        f"{context_text}\n\n用户问题：{request.message}"
        if context
        else request.message
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *[message.model_dump() for message in request.history],
        {"role": "user", "content": user_content},
    ]


def _provider_error() -> AiClientError:
    return AiClientError("AI_PROVIDER_ERROR", "AI 服务暂时不可用，请稍后重试")


def _read_content(value: object) -> str:
    if not isinstance(value, dict):
        raise _provider_error()
    choices = value.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _provider_error()
    first = choices[0]
    if not isinstance(first, dict):
        raise _provider_error()
    message = first.get("message")
    if not isinstance(message, dict):
        raise _provider_error()
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise _provider_error()
    return content.strip()


def _read_delta(value: object) -> str:
    if not isinstance(value, dict):
        raise _provider_error()
    choices = value.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _provider_error()
    first = choices[0]
    if not isinstance(first, dict):
        raise _provider_error()
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


class OpenAICompatibleChatClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http_client = http_client

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if not self._settings.ai_api_key:
            raise AiClientError("AI_NOT_CONFIGURED", "AI 服务尚未配置 API key")

        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(
            timeout=self._settings.ai_timeout_ms / 1000
        )
        try:
            response = await client.post(
                f"{self._settings.ai_base_url.rstrip('/')}/chat/completions",
                headers={
                    "authorization": f"Bearer {self._settings.ai_api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self._settings.ai_model,
                    "messages": build_provider_messages(request),
                    "temperature": 0.7,
                    "max_tokens": 1200,
                },
            )
            if response.status_code >= 400:
                raise _provider_error()
            try:
                content = _read_content(response.json())
            except (ValueError, TypeError):
                raise _provider_error() from None
            return ChatResponse(message={"role": "assistant", "content": content})
        except AiClientError:
            raise
        except httpx.TimeoutException:
            raise AiClientError("AI_PROVIDER_TIMEOUT", "AI 服务响应超时，请稍后重试") from None
        except httpx.RequestError:
            raise _provider_error() from None
        finally:
            if owns_client:
                await client.aclose()

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        if not self._settings.ai_api_key:
            raise AiClientError("AI_NOT_CONFIGURED", "AI 服务尚未配置 API key")

        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(
            timeout=self._settings.ai_timeout_ms / 1000
        )
        try:
            async with client.stream(
                "POST",
                f"{self._settings.ai_base_url.rstrip('/')}/chat/completions",
                headers={
                    "authorization": f"Bearer {self._settings.ai_api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self._settings.ai_model,
                    "messages": build_provider_messages(request),
                    "temperature": 0.7,
                    "max_tokens": 1200,
                    "stream": True,
                },
            ) as response:
                if response.status_code >= 400:
                    raise _provider_error()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        content = _read_delta(json.loads(payload))
                    except (ValueError, TypeError):
                        raise _provider_error() from None
                    if content:
                        yield content
        except AiClientError:
            raise
        except httpx.TimeoutException:
            raise AiClientError("AI_PROVIDER_TIMEOUT", "AI 服务响应超时，请稍后重试") from None
        except httpx.RequestError:
            raise _provider_error() from None
        finally:
            if owns_client:
                await client.aclose()
