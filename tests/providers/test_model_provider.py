import asyncio
from datetime import datetime, timezone

import pytest

from app.domain.chat import ChatResponse
from app.domain.trips import GeoPoint, VerifiedPoi
from app.model_provider import (
    ModelProviderError,
    NarrationRequest,
    OpenAIModelAdapter,
    ScheduleCandidate,
    ScheduleRequest,
)


class FakeChatClient:
    def __init__(self, contents: list[str]) -> None:
        self._contents = iter(contents)

    async def complete(self, request):
        return ChatResponse(
            message={"role": "assistant", "content": next(self._contents)}
        )


def verified_poi(uid: str) -> VerifiedPoi:
    return VerifiedPoi(
        uid=uid,
        name="真实景点",
        address="南京市真实地址",
        point=GeoPoint(lng=118.8, lat=32.06),
        opening_hours="09:00-18:00",
        recommended_stay_minutes=60,
        source="baidu",
        verified_at=datetime.now(timezone.utc),
    )


def valid_schedule_request() -> ScheduleRequest:
    return ScheduleRequest(
        destination="南京",
        days=1,
        message="南京一日游",
        candidates=(ScheduleCandidate("p1", "真实景点", "地址", "09:00-18:00"),),
    )


def test_real_model_adapter_accepts_candidate_uids_and_grounded_narration():
    adapter = OpenAIModelAdapter(
        FakeChatClient(
            [
                '{"days":[{"day":1,"poiUids":["p1"]}]}',
                '{"narration":[{"poiUid":"p1","text":"基于真实地址的讲解"}]}',
            ]
        )
    )

    async def run():
        schedule = await adapter.create_schedule(valid_schedule_request())
        narration = await adapter.create_narration(
            NarrationRequest(destination="南京", pois=(verified_poi("p1"),))
        )
        return schedule, narration

    schedule, narration = asyncio.run(run())

    assert schedule.days[0].day_index == 1
    assert schedule.days[0].poi_uids == ("p1",)
    assert narration.by_poi_uid == {"p1": "基于真实地址的讲解"}


def test_real_model_adapter_rejects_unknown_schedule_uid():
    adapter = OpenAIModelAdapter(
        FakeChatClient(['{"days":[{"day":1,"poiUids":["not-real"]}]}'])
    )

    with pytest.raises(ModelProviderError) as error:
        asyncio.run(adapter.create_schedule(valid_schedule_request()))

    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_real_model_adapter_rejects_extra_keys_and_duplicate_narration():
    adapter = OpenAIModelAdapter(
        FakeChatClient(
            [
                '{"days":[{"day":1,"poiUids":["p1"]}],"extra":true}',
            ]
        )
    )
    with pytest.raises(ModelProviderError) as schedule_error:
        asyncio.run(adapter.create_schedule(valid_schedule_request()))

    adapter = OpenAIModelAdapter(
        FakeChatClient(
            ['{"narration":[{"poiUid":"p1","text":"一"},{"poiUid":"p1","text":"二"}]}']
        )
    )
    with pytest.raises(ModelProviderError) as narration_error:
        asyncio.run(
            adapter.create_narration(
                NarrationRequest(destination="南京", pois=(verified_poi("p1"),))
            )
        )

    assert schedule_error.value.code == "MODEL_OUTPUT_INVALID"
    assert narration_error.value.code == "MODEL_OUTPUT_INVALID"
