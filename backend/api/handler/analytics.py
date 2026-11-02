"""市场分析看板：8 组聚合接口。"""

from __future__ import annotations

from backend.dto import params
from backend.httpkit.response import ApiError
from backend.service import analytics_service


def district_summary(ctx):
    return analytics_service.district_summary()


def price_distribution(ctx):
    return analytics_service.distribution(params.distribution(ctx))


def area_price_scatter(ctx):
    district_id = ctx.qi("district_id", lo=1)
    limit = ctx.qi("limit", 500, lo=1, hi=2890) or 500
    return analytics_service.scatter(district_id, limit)


def age_price_trend(ctx):
    return analytics_service.age_trend(ctx.qi("district_id", lo=1))


def age_price_by_district(ctx):
    top_n = ctx.qi("top_n", 6, lo=1, hi=17) or 6
    return analytics_service.age_by_district(top_n)


def premium(ctx):
    return analytics_service.premium(params.premium(ctx))


def floor_orientation(ctx):
    metric = (ctx.qs("metric") or "both").strip()
    if metric not in ("floor", "orientation", "both"):
        raise ApiError(1001, "metric 只支持 floor / orientation / both")
    return analytics_service.floor_orientation(metric)
