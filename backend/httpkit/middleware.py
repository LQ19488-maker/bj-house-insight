"""中间件：RequestID / Logger / CORS / Auth / Recovery。

在本项目里"中间件链"是显式编排的函数序列（见 server.py），
每层职责单一、可单独测试，不依赖任何框架的钩子机制。
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

from .ctx import Ctx
from .response import ApiError
from .router import ADMIN, LOGIN, OPTIONAL, Route

WHITE_LIST_PREFIX = ("/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/register")


# ---------------------------------------------------------------------------
# RequestID
# ---------------------------------------------------------------------------
def new_request_id() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Logger：JSON 单行输出到 stdout，便于 PaaS 采集
# ---------------------------------------------------------------------------
def log_access(ctx: Ctx, status: int, code: int, started_at: float) -> None:
    if os.environ.get("LOG_ACCESS") == "0":
        return
    took = (time.perf_counter() - started_at) * 1000
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "request_id": ctx.request_id,
        "method": ctx.method,
        "path": ctx.path,
        "route": ctx.route_name,
        "status": status,
        "code": code,
        "took_ms": round(took, 1),
        "user_id": ctx.user_id,
    }
    stream = sys.stdout
    print(json.dumps(record, ensure_ascii=False), file=stream, flush=True)
    if took > 500:
        record["level"] = "WARN"
        record["note"] = "slow request (>500ms)"
        print(json.dumps(record, ensure_ascii=False), file=stream, flush=True)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
def cors_headers(origin: str | None) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin or "*",
        "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Max-Age": "600",
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def check_auth(route: Route, ctx: Ctx, verify_token) -> None:
    """按路由的鉴权级别校验，把用户信息挂到 ctx.user。"""
    auth_header = ctx.headers.get("authorization") or ctx.headers.get("Authorization") or ""
    token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""

    if token:
        ctx.user = verify_token(token)  # 过期/非法会抛 ApiError(2002/2001)
    elif route.auth in (LOGIN, ADMIN):
        raise ApiError(2001)

    if route.auth == ADMIN and (not ctx.user or ctx.user.get("role") != "admin"):
        raise ApiError(2003)

    if route.auth == OPTIONAL and ctx.user is None:
        pass  # 匿名可用


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------
def recover(exc: BaseException) -> tuple[ApiError, bool]:
    """返回 (要返回给客户端的错误, 是否为未知异常)。未知异常不外泄堆栈。"""
    if isinstance(exc, ApiError):
        return exc, False
    return ApiError(5000), True
