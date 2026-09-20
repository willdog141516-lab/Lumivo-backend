import json

from fastapi.testclient import TestClient

from app.domain.chat import ChatResponse
from app.fixtures_nanjing import nanjing_planning_result
from app.main import create_app
from app.settings import Settings


class FakeChatClient:
    def __init__(self, content: str = "这是测试回复。") -> None:
        self.content = content
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return ChatResponse(message={"role": "assistant", "content": self.content})

    async def stream(self, request):
        self.calls += 1
        yield "流式"
        yield "回复。"


def make_client(chat_client: FakeChatClient) -> TestClient:
    return TestClient(
        create_app(
            Settings(ai_model="test-model", provider_mode="fixture", _env_file=None),
            chat_client=chat_client,
        )
    )


def test_legacy_health_reports_model_without_provider_call():
    chat_client = FakeChatClient()

    response = make_client(chat_client).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": "test-model"}
    assert chat_client.calls == 0


def test_chat_returns_injected_provider_response():
    chat_client = FakeChatClient("这是 Python 后端回复。")

    response = make_client(chat_client).post(
        "/api/chat",
        json={
            "message": "帮我规划成都三日游",
            "destination": "成都",
            "days": 3,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": {"role": "assistant", "content": "这是 Python 后端回复。"}
    }
    assert chat_client.calls == 1


def test_chat_streams_sse_when_requested():
    chat_client = FakeChatClient()

    response = make_client(chat_client).post(
        "/api/chat",
        headers={"accept": "text/event-stream"},
        json={"message": "给我一个旅行建议"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: delta\ndata: {"content": "流式"}' in response.text
    assert 'event: delta\ndata: {"content": "回复。"}' in response.text
    assert "event: done" in response.text
    assert chat_client.calls == 1


def test_chat_rejects_invalid_input_before_calling_provider():
    chat_client = FakeChatClient()

    response = make_client(chat_client).post("/api/chat", json={"message": ""})

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "INVALID_REQUEST", "message": "message 不能为空"}
    }
    assert chat_client.calls == 0


def test_unknown_endpoint_returns_not_found_error_code():
    response = make_client(FakeChatClient()).get("/api/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "\u8bf7\u6c42\u7684\u63a5\u53e3\u4e0d\u5b58\u5728"}
    }


def test_unsupported_method_returns_method_not_allowed_error_code():
    response = make_client(FakeChatClient()).get("/api/chat")

    assert response.status_code == 405
    assert response.json() == {
        "error": {"code": "METHOD_NOT_ALLOWED", "message": "\u8bf7\u6c42\u65b9\u6cd5\u4e0d\u652f\u6301"}
    }


def test_oversized_body_returns_request_too_large_error_code():
    response = make_client(FakeChatClient()).post(
        "/api/chat",
        content=b"x" * (64 * 1024 + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": {"code": "REQUEST_TOO_LARGE", "message": "\u8bf7\u6c42\u4f53\u4e0d\u80fd\u8d85\u8fc7 64 KiB"}
    }


def test_nanjing_plan_returns_frontend_compatible_result():
    selection = {
        "days": [
            {
                "day": 1,
                "poiUids": [
                    "fixture-nanjing-fuzimiao",
                    "fixture-nanjing-zhonghuamen",
                    "fixture-nanjing-laomendong",
                ],
            },
            {
                "day": 2,
                "poiUids": [
                    "fixture-nanjing-presidential-palace",
                    "fixture-nanjing-six-dynasties-museum",
                    "fixture-nanjing-museum",
                ],
            },
            {
                "day": 3,
                "poiUids": [
                    "fixture-nanjing-xuanwu-lake",
                    "fixture-nanjing-jiming-temple",
                    "fixture-nanjing-taicheng",
                ],
            },
        ]
    }
    chat_client = FakeChatClient(json.dumps(selection, ensure_ascii=False))

    response = make_client(chat_client).post(
        "/api/trips/plan",
        json={"message": "我计划去南京玩三天", "destination": "南京", "days": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["id"] == "fixture-nanjing-3d"
    assert body["plan"]["days"][0]["day"] == 1
    assert body["plan"]["days"][0]["routeLegs"][0]["fromPoiUid"] == "fixture-nanjing-fuzimiao"
    assert body["timeline"]["tripId"] == body["plan"]["id"]
    assert body["timeline"]["tripVersion"] == body["plan"]["version"]
    assert body["timeline"]["durationMs"] > 0


def test_unsupported_destination_stops_before_provider_call():
    chat_client = FakeChatClient()

    response = make_client(chat_client).post(
        "/api/trips/plan",
        json={"message": "东京三日游", "destination": "东京", "days": 3},
    )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "UNSUPPORTED_REGION",
        "message": "暂不支持该地区，等待后续开发",
    }
    assert chat_client.calls == 0


def test_invalid_model_selection_is_not_playable():
    chat_client = FakeChatClient('{"days": []}')

    response = make_client(chat_client).post(
        "/api/trips/plan",
        json={"message": "我计划去南京玩三天", "destination": "南京", "days": 3},
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "MODEL_OUTPUT_INVALID",
        "message": "AI 返回的行程选择无法通过校验",
    }


def test_full_real_without_baidu_key_does_not_fall_back_to_fixture():
    response = TestClient(
        create_app(Settings(provider_mode="full-real", _env_file=None))
    ).post(
        "/api/trips/plan",
        json={"message": "南京一日游", "destination": "南京", "days": 1},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MAP_PROVIDER_ERROR"


def test_real_planner_keeps_the_plan_and_timeline_response_contract():
    class FakeRealPlanner:
        async def plan(self, request):
            return nanjing_planning_result()

    response = TestClient(
        create_app(
            Settings(provider_mode="full-real"),
            planner=FakeRealPlanner(),
        )
    ).post(
        "/api/trips/plan",
        json={"message": "南京一日游", "destination": "南京", "days": 1},
    )

    assert response.status_code == 200
    assert set(response.json()) == {"plan", "timeline"}
