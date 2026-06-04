from datetime import datetime
from uuid import UUID
from typing import Optional

from pydantic import BaseModel


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
    bio: Optional[str] = None
    interests: Optional[list[str]] = None
    city: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    birth_year: Optional[int] = None
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
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    interests: Optional[list[str]] = None
    city: Optional[str] = None
    occupation: Optional[str] = None
    custom_interests: Optional[str] = None
    welcome_disturb: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


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


class AgentChatResponse(BaseModel):
    reply: str
    event_ready: bool = False
    event_id: Optional[UUID] = None
    event_draft_pending: bool = False


# ── Agent Memory ──

class MemoryResponse(BaseModel):
    id: UUID
    type: str
    content: str
    confidence: float
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


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


class EventUpdate(BaseModel):
    title: Optional[str] = None
    activity_type: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = None
    city: Optional[str] = None
    preferences: Optional[list[str]] = None
    constraints: Optional[list[str]] = None


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
