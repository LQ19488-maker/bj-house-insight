"""房源检索 / 详情 / 相似 / 对比 / 性价比异常。

handler 只做三件事：绑定参数 → 调用 service → 返回 data。
这里不出现任何 SQL，也不出现任何业务规则——由 tools/check_layers.py 静态保证。
"""

from __future__ import annotations

from backend.dto import params
from backend.httpkit.response import ApiError
from backend.service import house_service


def list_houses(ctx):
    p = params.search(ctx)
    sort, order = params.sort_order(ctx)
    page_no, size = params.page(ctx)
    return house_service.search(p, sort, order, page_no, size)


def detail(ctx):
    return house_service.detail(params.path_int(ctx))


def similar(ctx):
    limit = ctx.qi("limit", 5, lo=1, hi=20) or 5
    return house_service.similar(params.path_int(ctx), limit)


def compare(ctx):
    raw = ctx.qs("ids") or ""
    ids: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ids.append(int(token))
        except ValueError:
            raise ApiError(1001, "ids 必须是逗号分隔的整数")
    return house_service.compare(ids)


def anomaly(ctx):
    district_id = ctx.qi("district_id", lo=1)
    band = (ctx.qs("area_band") or "60-90").strip()
    if band not in params.AREA_BANDS:
        raise ApiError(1001, f"area_band 只支持 {', '.join(params.AREA_BANDS)}")
    threshold = ctx.qf("threshold", 0.20) or 0.20
    if not (0.05 <= threshold <= 0.50):
        raise ApiError(1001, "threshold 必须在 0.05–0.50 之间")
    limit = ctx.qi("limit", 20, lo=1, hi=100) or 20
    return house_service.anomaly(district_id, band, threshold, limit)
