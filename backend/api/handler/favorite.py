"""收藏（幂等）。"""

from __future__ import annotations

from backend.dto import params
from backend.service import auth_service


def add(ctx):
    user = ctx.require_login()
    return auth_service.favorite_add(int(user["user_id"]), params.path_int(ctx, "house_id"))


def remove(ctx):
    user = ctx.require_login()
    return auth_service.favorite_remove(int(user["user_id"]), params.path_int(ctx, "house_id"))


def list_favorites(ctx):
    user = ctx.require_login()
    page_no, size = params.page(ctx)
    return auth_service.favorite_list(int(user["user_id"]), page_no, size)
