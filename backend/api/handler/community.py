"""小区画像与排行。"""

from __future__ import annotations

from backend.dto import params
from backend.httpkit.response import ApiError
from backend.service import catalog_service


def community(ctx):
    return catalog_service.community(params.path_int(ctx))


def rankings(ctx):
    scope = (ctx.qs("scope") or "").strip()
    if scope not in ("community", "street"):
        raise ApiError(1001, "scope 只支持 community / street")
    by = (ctx.qs("by") or "avg_unit_price").strip()
    if by not in ("avg_unit_price", "house_count"):
        raise ApiError(1002, "by 只支持 avg_unit_price / house_count")
    order = (ctx.qs("order") or "desc").strip().lower()
    if order not in ("asc", "desc"):
        raise ApiError(1001, "order 只支持 asc / desc")
    min_count = ctx.qi("min_count", 3, lo=1, hi=100) or 3
    include_pseudo = ctx.qb("include_pseudo", False) or False
    limit = ctx.qi("limit", 20, lo=1, hi=100) or 20
    return catalog_service.rankings(scope, by, order, min_count, include_pseudo, limit)
