"""维度字典：区 / 街道 / 筛选项枚举与取值范围。"""

from __future__ import annotations

from backend.service import catalog_service


def districts(ctx):
    return catalog_service.districts()


def streets(ctx):
    district_id = ctx.qi("district_id", lo=1)
    include_pseudo = ctx.qb("include_pseudo", False) or False
    return catalog_service.streets(district_id, include_pseudo)


def filters(ctx):
    return catalog_service.filters()
