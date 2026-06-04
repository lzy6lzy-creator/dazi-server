"""
WebSocket API - 实时消息推送

功能：
- 用户连接 WebSocket 后，实时接收聊天室消息、事件状态更新
- 替代客户端 30 秒轮询
- token 通过 query param 传递（WebSocket 不支持自定义 header）
"""
from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError, jwt

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """管理所有活跃的 WebSocket 连接"""

    def __init__(self):
        # user_id -> list of WebSocket connections (同一用户可能多设备)
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        if user_id not in self._connections:
            self._connections[user_id] = []
        self._connections[user_id].append(ws)
        logger.info(f"WebSocket connected: user={user_id}, total={self.count}")

    def disconnect(self, user_id: str, ws: WebSocket):
        if user_id in self._connections:
            self._connections[user_id] = [
                c for c in self._connections[user_id] if c is not ws
            ]
            if not self._connections[user_id]:
                del self._connections[user_id]
        logger.info(f"WebSocket disconnected: user={user_id}, total={self.count}")

    async def send_to_user(self, user_id: str, data: dict):
        """向指定用户的所有连接发送消息"""
        conns = self._connections.get(user_id, [])
        dead = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        # 清理断开的连接
        for ws in dead:
            self.disconnect(user_id, ws)

    async def broadcast_to_users(self, user_ids: list[str], data: dict):
        """向多个用户广播消息"""
        for uid in user_ids:
            await self.send_to_user(uid, data)

    @property
    def count(self) -> int:
        return sum(len(v) for v in self._connections.values())


# 全局连接管理器
manager = ConnectionManager()


def _authenticate_token(token: str) -> str | None:
    """验证 JWT token，返回 user_id 或 None"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload.get("user_id")
    except JWTError:
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    token: str = Query(...),
):
    """
    WebSocket 端点

    连接: ws://host/ws?token=<jwt_access_token>

    服务端推送消息格式:
    {
        "type": "new_message",
        "room_id": "...",
        "message": { ... }
    }
    {
        "type": "event_update",
        "event_id": "...",
        "status": "..."
    }
    {
        "type": "room_created",
        "room": { ... }
    }

    客户端可发送 ping:
    { "type": "ping" }
    服务端回复:
    { "type": "pong" }
    """
    user_id = _authenticate_token(token)
    if not user_id:
        await ws.close(code=4001, reason="Invalid token")
        return

    await manager.connect(user_id, ws)
    try:
        while True:
            # 等待客户端消息（主要用于 ping/pong 保活）
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(user_id, ws)
    except Exception as e:
        logger.error(f"WebSocket error for user={user_id}: {e}")
        manager.disconnect(user_id, ws)
