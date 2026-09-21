import asyncio
from datetime import datetime, timezone

import pytest

from app.domain.chat import ChatMessage, ChatResponse, TripPlanRequest
from app.domain.trips import GeoPoint, TravelMode, VerifiedPoi
from app.model_provider import (
    ModelProviderError,
    NarrationRequest,
    OpenAIModelAdapter,
    RevisionRequest,
    ScheduleCandidate,
    ScheduleRequest,
)


class FakeChatClient:
    def __init__(self, contents: list[str]) -> None:
        self._contents = iter(contents)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
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
                '{"days":[{"day":1,"poiUids":["p1"],"transportModes":[]}]}',
                '{"narration":[{"poiUid":"p1","text":"真实景点位于真实地址附近。"}]}',
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
    assert narration.by_poi_uid == {"p1": "真实景点位于真实地址附近。"}


def test_real_model_adapter_accepts_valid_revision_uids():
    adapter = OpenAIModelAdapter(
        FakeChatClient(['{"day":2,"poiUids":["p1","p2"],"transportModes":["walk"]}'])
    )
    request = RevisionRequest(
        destination="南京",
        day_index=2,
        instruction="增加一个博物馆",
        current_poi_uids=("p1",),
        candidates=(
            ScheduleCandidate("p1", "真实景点", "地址 1", "09:00-18:00"),
            ScheduleCandidate("p2", "另一个景点", "地址 2", "09:00-18:00"),
        ),
    )

    revision = asyncio.run(adapter.revise_day(request))

    assert revision.day_index == 2
    assert revision.poi_uids == ("p1", "p2")
    assert revision.transport_modes == (TravelMode.WALK,)

def test_real_model_adapter_uses_the_requested_revision_day_in_prompt():
    client = FakeChatClient(
        ['{"day":1,"poiUids":["p1"],"transportModes":[]}']
    )
    adapter = OpenAIModelAdapter(client)
    request = RevisionRequest(
        destination="南京",
        day_index=1,
        instruction="换一个景点",
        current_poi_uids=("p1",),
        candidates=(ScheduleCandidate("p1", "真实景点", "地址", None),),
    )

    asyncio.run(adapter.revise_day(request))

    assert '"day":1' in client.requests[0].message
    assert '"day":2' not in client.requests[0].message


def test_real_model_adapter_extracts_trip_intent_from_dialogue():
    adapter = OpenAIModelAdapter(
        FakeChatClient(['{"destination":"成都","days":3}'])
    )

    intent = asyncio.run(
        adapter.extract_trip_intent(
            TripPlanRequest(
                message="请把上面的聊天生成成故事地图",
                history=(
                    ChatMessage(role="user", content="我想去成都玩三天，重点看老街"),
                    ChatMessage(role="assistant", content="可以安排慢一点。"),
                ),
            )
        )
    )

    assert intent.destination == "成都"
    assert intent.days == 3

@pytest.mark.parametrize(
    "content",
    [
        '{"day":2,"poiUids":["unknown"],"transportModes":[]}',
        '{"day":2,"poiUids":["p1","p1"],"transportModes":["walk"]}',
    ],
)
def test_real_model_adapter_rejects_invalid_revision_uids(content):
    adapter = OpenAIModelAdapter(FakeChatClient([content]))
    request = RevisionRequest(
        destination="南京",
        day_index=2,
        instruction="调整路线",
        current_poi_uids=("p1",),
        candidates=(ScheduleCandidate("p1", "真实景点", "地址", None),),
    )

    with pytest.raises(ModelProviderError) as error:
        asyncio.run(adapter.revise_day(request))

    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_real_model_adapter_rejects_narration_without_name_anchor():
    adapter = OpenAIModelAdapter(
        FakeChatClient(
            ['{"narration":[{"poiUid":"p1","text":"根据地址写出的讲解"}]}']
        )
    )

    with pytest.raises(ModelProviderError) as error:
        asyncio.run(
            adapter.create_narration(
                NarrationRequest(destination="南京", pois=(verified_poi("p1"),))
            )
        )

    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_real_model_adapter_rejects_unknown_schedule_uid():
    adapter = OpenAIModelAdapter(
        FakeChatClient(['{"days":[{"day":1,"poiUids":["not-real"],"transportModes":[]}]}'])
    )

    with pytest.raises(ModelProviderError) as error:
        asyncio.run(adapter.create_schedule(valid_schedule_request()))

    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_real_model_adapter_rejects_extra_keys_and_duplicate_narration():
    adapter = OpenAIModelAdapter(
        FakeChatClient(
            [
                '{"days":[{"day":1,"poiUids":["p1"],"transportModes":[]}],"extra":true}',
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

def test_real_model_adapter_parses_transport_modes_for_route_legs():
    adapter = OpenAIModelAdapter(
        FakeChatClient(
            ['{"days":[{"day":1,"poiUids":["p1","p2"],"transportModes":["transit"]}]}']
        )
    )
    request = ScheduleRequest(
        destination="南京",
        days=1,
        message="南京一日游",
        candidates=(
            ScheduleCandidate("p1", "起点", "地址1", None),
            ScheduleCandidate("p2", "终点", "地址2", None),
        ),
    )

    schedule = asyncio.run(adapter.create_schedule(request))

    assert schedule.days[0].transport_modes == ("transit",)