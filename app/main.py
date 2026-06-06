"""
i搭不搭 - Backend API Server
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.core.database import engine, Base, async_session
from app.core.config import settings
from app.core.redis import close_redis
from app.core.log_buffer import log_buffer
from app.services.agent_server import agent_server
from app.services.embedding_service import embedding_service
from app.services.scheduler import match_scheduler

# 导入所有 model 以确保建表时能发现它们
from app.models.user import User, Agent, AgentMemory, EventMemory, MemoryEvidence, AgentChatMessage, PushDeviceToken  # noqa: F401
from app.models.event import Event, MatchLog, MatchBlocklist  # noqa: F401
from app.models.chat import ChatRoom, ChatRoomMember, ChatMessage, ChatRoomVote, PassiveMatchRequest  # noqa: F401
from app.models.prompt import PromptTemplate  # noqa: F401
from app.models.beta_signup import BetaSignup  # noqa: F401
from app.models.site_feedback import SiteFeedback  # noqa: F401

# 导入路由
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.events import router as events_router
from app.api.agent_chat import router as agent_chat_router
from app.api.chat import router as chat_router
from app.api.beta import router as beta_router
from app.api.feedback import router as feedback_router
from app.api.admin import router as admin_router
from app.api.ws import router as ws_router
from app.api.notifications import router as notifications_router

# 配置日志 + 内存缓冲区
log_buffer.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        log_buffer,
    ],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Config loaded: DATABASE_URL and JWT_SECRET provided via environment.")

    # 检查 JWT_SECRET 是否有效
    if not settings.JWT_SECRET or len(settings.JWT_SECRET) < 8:
        logging.warning(
            "CRITICAL: JWT_SECRET is empty or too short (< 8 chars). "
            "This is insecure for production. Set a strong JWT_SECRET in environment variables."
        )

    # 启动时建表 + 启用 pgvector 扩展
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_runtime_schema(conn)
    logging.info("Database tables created.")

    # 从 DB 加载 prompt 覆盖到内存
    from sqlalchemy import select as sa_select
    from app.services.prompt_builder import PromptBuilder
    async with async_session() as db:
        result = await db.execute(sa_select(PromptTemplate))
        for row in result.scalars().all():
            if row.name in PromptBuilder._TEMPLATES:
                PromptBuilder.override_template(row.name, row.content)
                logging.info(f"Loaded prompt override: {row.name}")

    # 初始化统一 agent server 客户端
    agent_server.start()

    # 启动定时匹配任务（每小时扫描 pending 事件）
    match_scheduler.start()

    yield
    # 关闭时清理资源
    await match_scheduler.stop()
    await agent_server.close()
    await embedding_service.close()
    await close_redis()
    await engine.dispose()
    logging.info("Resources cleaned up.")


async def _ensure_runtime_schema(conn) -> None:
    """Backfill additive columns for existing databases.

    The project currently creates tables at startup instead of running Alembic
    revisions, so additive schema changes need a lightweight runtime guard.
    """
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS birth_date DATE"))
    await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS clarification_answers JSONB"))
    await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS age_filter_min INTEGER"))
    await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS age_filter_max INTEGER"))
    await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS age_filter_mode VARCHAR(20)"))
    await conn.execute(text("ALTER TABLE match_logs ADD COLUMN IF NOT EXISTS score_breakdown JSONB"))
    await conn.execute(text("ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS key VARCHAR(100)"))
    await conn.execute(text("ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS category VARCHAR(40)"))
    await conn.execute(text("ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS scope VARCHAR(20) DEFAULT 'long_term'"))
    await conn.execute(text("ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS value JSONB"))
    await conn.execute(text("ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS occurrence_count INTEGER DEFAULT 1"))
    await conn.execute(text("ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ"))
    await conn.execute(text("ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"))
    await conn.execute(text("ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active'"))
    await conn.execute(text("ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS superseded_by_id UUID"))
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_push_device_tokens_token_unique ON push_device_tokens(token)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_push_device_tokens_user_active ON push_device_tokens(user_id, is_active)"))


app = FastAPI(
    title="i搭不搭 API",
    description="AI Agent 社交搭子匹配平台",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS - 限制允许的来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8080",
        "http://47.103.127.95:8000",
        "http://47.103.127.95",
        "https://idabuda.com",
        "https://www.idabuda.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(events_router)
app.include_router(agent_chat_router)
app.include_router(chat_router)
app.include_router(beta_router)
app.include_router(feedback_router)
app.include_router(admin_router)
app.include_router(ws_router)
app.include_router(notifications_router)

# 静态文件
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def root():
    """介绍网站首页"""
    return FileResponse("app/static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin")
async def admin_page():
    """管理后台页面"""
    return FileResponse("app/static/admin.html")


@app.get("/test")
async def test_page():
    """综合测试页面"""
    return FileResponse("app/static/test.html")


@app.get("/match-test")
async def match_test_page():
    """匹配系统测试可视化页面"""
    return FileResponse("app/static/admin.html")
