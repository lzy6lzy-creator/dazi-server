"""
Auth API - 用户注册/登录

内部测试阶段：
- 用手机号 + 6位验证码登录
- 验证码必须通过环境变量显式配置，并限制手机号白名单
- 首次登录自动注册
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models.user import User, Agent
from app.api.auth_helpers import is_valid_internal_test_code
from app.api.schemas import (
    AuthSendCodeRequest,
    AuthLoginRequest,
    AuthTokenResponse,
    AuthRefreshRequest,
    UserCreate,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/send-code")
async def send_code(req: AuthSendCodeRequest):
    """内部测试发送验证码占位：只允许白名单手机号进入登录流程。"""
    if not settings.INTERNAL_TEST_MODE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="短信服务暂未配置",
        )

    if not is_valid_internal_test_code(
        phone=req.phone,
        submitted_code=settings.INTERNAL_TEST_CODE,
        enabled=settings.INTERNAL_TEST_MODE,
        configured_code=settings.INTERNAL_TEST_CODE,
        allowed_phones_csv=settings.INTERNAL_TEST_PHONES,
        allowed_phones_file=settings.INTERNAL_TEST_PHONES_FILE,
    ):
        raise HTTPException(status_code=403, detail="该手机号未加入内部测试白名单")

    # TODO: 接入 SMS 服务（阿里云/腾讯云短信）后替换为真实发送。
    return {"message": "验证码已发送"}


@router.post("/login")
async def login(req: AuthLoginRequest, db: AsyncSession = Depends(get_db)):
    """手机号 + 验证码登录，首次登录自动注册"""
    # 验证码校验
    if not is_valid_internal_test_code(
        phone=req.phone,
        submitted_code=req.code,
        enabled=settings.INTERNAL_TEST_MODE,
        configured_code=settings.INTERNAL_TEST_CODE,
        allowed_phones_csv=settings.INTERNAL_TEST_PHONES,
        allowed_phones_file=settings.INTERNAL_TEST_PHONES_FILE,
    ):
        raise HTTPException(status_code=400, detail="验证码错误")

    # 查找用户
    result = await db.execute(select(User).where(User.phone == req.phone))
    user = result.scalar_one_or_none()

    is_new = False
    if not user:
        # 首次登录 → 自动注册
        user = User(phone=req.phone, name=f"用户{req.phone[-4:]}")
        db.add(user)
        await db.flush()

        # 创建默认 Agent
        agent = Agent(user_id=user.id, name="点点", emoji="🤖")
        db.add(agent)
        await db.flush()
        is_new = True

    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "user_id": str(user.id),
        "is_new_user": is_new,
    }


@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh_token(req: AuthRefreshRequest, db: AsyncSession = Depends(get_db)):
    """用 refresh_token 换取新的 access_token"""
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=400, detail="Invalid token type")

    user_id = UUID(payload["user_id"])

    return AuthTokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
        user_id=user_id,
        is_new_user=False,
    )
