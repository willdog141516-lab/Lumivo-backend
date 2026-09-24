from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.trips import TravelMode, TripPlan, TripReroutePlan


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content 不能为空")
        if len(value) > 4000:
            raise ValueError("content 长度不能超过 4000 个字符")
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    destination: str | None = Field(default=None, max_length=100)
    days: int | None = Field(default=None, ge=1, le=30)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message 不能为空")
        if len(value) > 4000:
            raise ValueError("message 长度不能超过 4000 个字符")
        return value

    @field_validator("destination")
    @classmethod
    def normalize_destination(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class TripPlanRequest(ChatRequest):
    destination: str | None = Field(default=None, max_length=100)
    days: int | None = Field(default=None, ge=1, le=30)
    transport: TravelMode | None = None


class TripRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: TripPlan
    day: int = Field(ge=1)
    instruction: str

    @field_validator("instruction")
    @classmethod
    def instruction_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("instruction 不能为空")
        if len(value) > 4000:
            raise ValueError("instruction 长度不能超过 4000 个字符")
        return value

    @model_validator(mode="after")
    def day_must_exist_in_plan(self) -> "TripRevisionRequest":
        if self.day > len(self.plan.days):
            raise ValueError("day 必须存在于当前计划")
        return self


class TripRerouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: TripReroutePlan
    transport: TravelMode


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatResponse(BaseModel):
    message: AssistantMessage
