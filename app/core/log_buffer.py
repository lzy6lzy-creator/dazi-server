"""
内存日志缓冲区 - 供管理页面实时查看日志
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone


class LogBuffer(logging.Handler):
    """将日志存入内存 deque，供 API 读取"""

    def __init__(self, max_lines: int = 500):
        super().__init__()
        self.buffer = deque(maxlen=max_lines)

    def emit(self, record):
        try:
            entry = {
                "time": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            }
            self.buffer.append(entry)
        except Exception:
            pass

    def get_logs(self, limit: int = 100, level: str | None = None) -> list[dict]:
        logs = list(self.buffer)
        if level:
            logs = [l for l in logs if l["level"] == level.upper()]
        return logs[-limit:]

    def clear(self):
        self.buffer.clear()


# 全局实例
log_buffer = LogBuffer(max_lines=500)
