import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai_client import AiClientError
from app.api.canonical import _stream_events, create_canonical_router
from app.domain.chat import TripPlanRequest, TripRevisionRequest
from app.fixtures_nanjing import nanjing_planning_result
from app.planning_service import ProgressCallback, TripPlannerError


def make_app(planner) -> FastAPI:
    application = FastAPI()
    application.include_router(create_canonical_router(planner))
    return application


def records(response) -> list[dict[str, object]]:
    return [json.loads(line) for line in response.text.splitlines() if line]


class StreamingPlanner:
    def __init__(self) -> None:
        self.revision_request: TripRevisionRequest | None = None

    async def plan(
        self,
        request: TripPlanRequest,
        *,
        progress: ProgressCallback | None = None,
    ):
        assert progress is not None
        await progress("destination.validated", {"destination": request.destination})
        await progress("timeline.ready", {})
        return nanjing_planning_result()

    async def revise(
        self,
        request: TripRevisionRequest,
        *,
        progress: ProgressCallback | None = None,
    ):
        self.revision_request = request
        assert progress is not None
        await progress("timeline.ready", {})
        return nanjing_planning_result()


class ErrorPlanner(StreamingPlanner):
    async def plan(self, request, *, progress=None):
        assert progress is not None
        await progress("destination.validated", {})
        raise TripPlannerError("MAP_PROVIDER_ERROR", "provider secret")


class AiErrorPlanner(StreamingPlanner):
    async def plan(self, request, *, progress=None):
        raise AiClientError("AI_PROVIDER_ERROR", "provider secret")


class InputRequiredPlanner(StreamingPlanner):
    async def plan(self, request, *, progress=None):
        raise TripPlannerError("PLAN_INPUT_REQUIRED", "请在对话中补充目的地")



def test_plan_streams_progress_and_completion():
    response = TestClient(make_app(StreamingPlanner())).post(
        "/api/v1/trips/plan",
        json={"message": "南京三日游", "destination": "南京", "days": 3},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert [record["event"] for record in records(response)] == [
        "planning.started",
        "destination.validated",
        "timeline.ready",
        "planning.completed",
    ]
    completed = records(response)[-1]["data"]
    assert completed["plan"]["id"] == "fixture-nanjing-3d"
    assert completed["timeline"]["tripId"] == "fixture-nanjing-3d"


def test_plan_stream_accepts_dialogue_without_explicit_destination_or_days():
    response = TestClient(make_app(StreamingPlanner())).post(
        "/api/v1/trips/plan",
        json={
            "message": "请根据上面的聊天生成故事地图",
            "history": [
                {"role": "user", "content": "我想去成都玩三天"},
                {"role": "assistant", "content": "可以。"},
            ],
        },
    )

    assert response.status_code == 200
    assert records(response)[-1]["event"] == "planning.completed"

def test_plan_stream_maps_provider_error_without_leaking_provider_message():
    response = TestClient(make_app(ErrorPlanner())).post(
        "/api/v1/trips/plan",
        json={"message": "南京三日游", "destination": "南京", "days": 3},
    )
    output = records(response)

    assert output[-1]["event"] == "planning.error"
    assert "provider secret" not in response.text
    assert "planning.completed" not in [record["event"] for record in output]
    assert output[-1]["error"] == {
        "code": "MAP_PROVIDER_ERROR",
        "message": "百度地图服务暂时不可用，请检查地图配置后重试",
        "retryable": True,
        "details": {},
    }


def test_plan_stream_maps_ai_provider_error_without_downgrading_to_internal_error():
    response = TestClient(make_app(AiErrorPlanner())).post(
        "/api/v1/trips/plan",
        json={"message": "南京三日游", "destination": "南京", "days": 3},
    )
    output = records(response)

    assert output[-1]["event"] == "planning.error"
    assert "provider secret" not in response.text
    assert output[-1]["error"] == {
        "code": "AI_PROVIDER_ERROR",
        "message": "AI 服务暂时不可用，请稍后重试",
        "retryable": True,
        "details": {},
    }


def test_plan_stream_maps_missing_trip_details_as_structured_error():
    response = TestClient(make_app(InputRequiredPlanner())).post(
        "/api/v1/trips/plan",
        json={"message": "请把这段聊天做成地图"},
    )

    output = records(response)

    assert output[-1]["event"] == "planning.error"
    assert output[-1]["error"] == {
        "code": "PLAN_INPUT_REQUIRED",
        "message": "请补充目的地和旅行天数",
        "retryable": False,
        "details": {},
    }

def test_plan_stream_rejects_invalid_input_before_streaming():
    response = TestClient(make_app(StreamingPlanner())).post(
        "/api/v1/trips/plan",
        json={"message": "", "destination": "", "days": 0},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_revision_stream_parses_the_complete_current_plan():
    planner = StreamingPlanner()
    plan = nanjing_planning_result().plan

    response = TestClient(make_app(planner)).post(
        "/api/v1/trips/revise",
        json={
            "plan": plan.model_dump(mode="json", by_alias=True),
            "day": 1,
            "instruction": "换一个景点",
        },
    )

    assert response.status_code == 200
    assert planner.revision_request is not None
    assert planner.revision_request.plan.id == plan.id
    assert records(response)[-1]["event"] == "planning.completed"


def test_stream_cancels_planner_when_request_disconnects():
    cancelled = asyncio.Event()

    class DisconnectingRequest:
        calls = 0

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls > 1

    async def slow_operation(progress: ProgressCallback):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def collect() -> list[dict[str, object]]:
        output = []
        async for line in _stream_events(
            DisconnectingRequest(),
            slow_operation,
            "request-id",
        ):
            output.append(json.loads(line))
        return output

    output = asyncio.run(collect())

    assert cancelled.is_set()
    assert [record["event"] for record in output] == ["planning.started"]
