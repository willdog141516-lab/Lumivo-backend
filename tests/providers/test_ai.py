import asyncio
import json

import httpx

from app.domain.chat import ChatRequest
from app.ai_client import OpenAICompatibleChatClient
from app.settings import Settings


def test_openai_compatible_client_sends_context_and_reads_content():
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "  provider reply  "}}]},
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = OpenAICompatibleChatClient(
                Settings(
                    ai_base_url="https://provider.example/v1",
                    ai_api_key="test-key",
                    ai_model="test-model",
                ),
                http_client=http_client,
            )
            response = await client.complete(
                ChatRequest(
                    message="帮我规划南京三日游",
                    destination="南京",
                    days=3,
                )
            )
            return response

    response = asyncio.run(run())

    assert response.message.content == "provider reply"
    assert seen["url"] == "https://provider.example/v1/chat/completions"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "test-model"
    assert body["messages"][-1]["content"].startswith("目的地：南京")


def test_openai_compatible_client_streams_delta_content():
    seen: dict[str, object] = {}

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield 'data: {"choices":[{"delta":{"content":"流式"}}]}\n\n'.encode()
            yield 'data: {"choices":[{"delta":{"content":"回复"}}]}\n\n'.encode()
            yield b"data: [DONE]\n\n"

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, stream=Stream())

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = OpenAICompatibleChatClient(
                Settings(ai_api_key="test-key"),
                http_client=http_client,
            )
            return [
                chunk
                async for chunk in client.stream(ChatRequest(message="继续"))
            ]

    chunks = asyncio.run(run())

    assert chunks == ["流式", "回复"]
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["stream"] is True
