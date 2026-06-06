from datetime import date, datetime
from uuid import UUID
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Auth ──

class AuthSendCodeRequest(BaseModel):
    phone: str


class AuthLoginRequest(BaseModel):
    phone: str
    code: str


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: UUID
    is_new_user: bool = False


class AuthRefreshRequest(BaseModel):
    refresh_token: str


# ── User ──

class UserCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    gender: Optional[str] = None
    birth_year: Optional[int] = None
    birth_date: Optional[date] = None
    bio: Optional[str] = None
    interests: Optional[list[str]] = None
    city: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    birth_year: Optional[int] = None
    birth_date: Optional[date] = None
    bio: Optional[str] = None
    interests: Optional[list[str]] = None
    city: Optional[str] = None
    occupation: Optional[str] = None
    custom_interests: Optional[str] = None
    welcome_disturb: Optional[bool] = None


class UserResponse(BaseModel):
    id: UUID
    name: str
    phone: Optional[str] = None
    gender: Optional[str] = None
    birth_year: Optional[int] = None
    birth_date: Optional[date] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    interests: Optional[list[str]] = None
    city: Optional[str] = None
    occupation: Optional[str] = None
    custom_interests: Optional[str] = None
    welcome_disturb: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicUserProfileResponse(BaseModel):
    id: UUID
    name: str
    gender: Optional[str] = None
    birth_year: Optional[int] = None
    birth_date: Optional[date] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    interests: Optional[list[str]] = None
    city: Optional[str] = None
    occupation: Optional[str] = None
    custom_interests: Optional[str] = None
    welcome_disturb: bool = False

    model_config = {"from_attributes": True}


# ── Notifications ──

class PushDeviceTokenRequest(BaseModel):
    token: str
    platform: str = "ios"
    environment: str = "production"

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, value):
        token = str(value or "").strip()
        if not token:
            raise ValueError("token 不能为空")
        return token

    @field_validator("platform", "environment", mode="before")
    @classmethod
    def normalize_label(cls, value):
        return str(value or "").strip().lower()

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value):
        if value not in {"ios"}:
            raise ValueError("platform 目前只支持 ios")
        return value

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value):
        if value not in {"production", "sandbox"}:
            raise ValueError("environment 必须是 production 或 sandbox")
        return value


class PushDeviceTokenResponse(BaseModel):
    registered: bool


# ── Agent ──

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    emoji: Optional[str] = None
    personality: Optional[str] = None


class AgentResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    emoji: Optional[str] = None
    avatar_url: Optional[str] = None
    personality: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Agent Chat ──

class AgentChatRequest(BaseModel):
    message: str
    current_location: Optional[str] = None


class ClarificationOption(BaseModel):
    id: str
    label: str
    value: Optional[Any] = None


class ClarificationQuestion(BaseModel):
    id: str
    type: str = "single_choice"
    title: str
    helper_text: Optional[str] = None
    category: Optional[str] = None
    required: bool = False
    allow_custom: bool = True
    match_filter: Optional[str] = None
    options: list[ClarificationOption] = Field(default_factory=list)
    default_option_ids: list[str] = Field(default_factory=list)


class ClarificationAnswer(BaseModel):
    question_id: str
    option_ids: Optional[list[str]] = None
    custom_value: Optional[Any] = None


class ClarificationAnswerRequest(BaseModel):
    clarification_session_id: str
    answers: list[ClarificationAnswer] = []
    free_text: Optional[str] = None


class ClarificationStreamAnswerRequest(ClarificationAnswerRequest):
    pass


class AgentChatResponse(BaseModel):
    reply: str
    event_ready: bool = False
    event_id: Optional[UUID] = None
    event_draft_pending: bool = False
    clarification_pending: bool = False
    clarification_session_id: Optional[str] = None
    clarification_questions: list[ClarificationQuestion] = []


# ── Agent Memory ──

class MemoryResponse(BaseModel):
    id: UUID
    type: str
    content: str
    confidence: float
    source: str
    key: Optional[str] = None
    category: Optional[str] = None
    scope: str = "long_term"
    value: Optional[dict[str, Any]] = None
    occurrence_count: int = 1
    last_seen_at: Optional[datetime] = None
    status: str = "active"
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    is_active: Optional[bool] = None
    status: Optional[str] = None

    @model_validator(mode="after")
    def validate_change(self):
        if self.content is None and self.is_active is None and self.status is None:
            raise ValueError("至少需要修改 content、is_active 或 status")
        if self.content is not None and not self.content.strip():
            raise ValueError("content 不能为空")
        if self.status is not None and self.status not in {"active", "inactive", "conflicted"}:
            raise ValueError("status 必须是 active、inactive 或 conflicted")
        return self


# ── Event ──

class EventCreate(BaseModel):
    title: str
    activity_type: str
    city: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = None
    preferences: Optional[list[str]] = None
    constraints: Optional[list[str]] = None
    clarification_answers: Optional[list[dict[str, Any]]] = None
    age_filter_min: Optional[int] = None
    age_filter_max: Optional[int] = None
    age_filter_mode: Optional[str] = None


class EventUpdate(BaseModel):
    title: Optional[str] = None
    activity_type: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = None
    city: Optional[str] = None
    preferences: Optional[list[str]] = None
    constraints: Optional[list[str]] = None
    clarification_answers: Optional[list[dict[str, Any]]] = None
    age_filter_min: Optional[int] = None
    age_filter_max: Optional[int] = None
    age_filter_mode: Optional[str] = None


class EventResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    activity_type: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = None
    city: Optional[str] = None
    preferences: Optional[list[str]] = None
    constraints: Optional[list[str]] = None
    clarification_answers: Optional[list[dict[str, Any]]] = None
    age_filter_min: Optional[int] = None
    age_filter_max: Optional[int] = None
    age_filter_mode: Optional[str] = None
    status: str
    match_score: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── ChatRoom ──

class ChatRoomMemberResponse(BaseModel):
    user_id: UUID
    name: str
    role: str  # "user" or "agent"
    emoji: Optional[str] = None
    avatar_url: Optional[str] = None


class ChatRoomResponse(BaseModel):
    id: UUID
    event_title: Optional[str] = None
    match_summary: Optional[str] = None
    is_active: bool
    created_at: datetime
    closed_at: Optional[datetime] = None
    members: list[ChatRoomMemberResponse] = []
    last_message: Optional["MessageResponse"] = None


class VoteRequest(BaseModel):
    vote: str  # "da" or "bu_da"


class VoteStatusResponse(BaseModel):
    my_vote: Optional[str] = None
    partner_vote: Optional[str] = None
    result: Optional[str] = None  # "matched" / "rejected" / "pending"


class PassiveMatchRequestResponse(BaseModel):
    id: UUID
    event_id: UUID
    event_title: str
    requester_name: str
    target_user_id: UUID
    status: str
    similarity: Optional[float] = None
    message: Optional[str] = None
    created_at: datetime


class PassiveMatchRequestAction(BaseModel):
    action: str  # accept / reject


class MessageCreate(BaseModel):
    content: str
    mentions: Optional[list[str]] = None


class MessageResponse(BaseModel):
    id: UUID
    room_id: UUID
    sender_id: UUID
    sender_type: str
    content: str
    mentions: Optional[list[str]] = None
    created_at: datetime

    model_config = {"from_attributes": True}
