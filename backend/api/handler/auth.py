"""注册 / 登录 / 当前用户。"""

from __future__ import annotations

from backend.dto import params
from backend.service import auth_service


def register(ctx):
    username, password = params.auth_body(ctx, for_register=True)
    return auth_service.register(username, password)


def login(ctx):
    username, password = params.auth_body(ctx)
    return auth_service.login(username, password)


def me(ctx):
    user = ctx.require_login()
    return auth_service.me(int(user["user_id"]))
