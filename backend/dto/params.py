"""请求参数解析与校验。所有 1001/1002/1003 都在这一层抛出。"""

from __future__ import annotations

from ..httpkit.ctx import Ctx
from ..httpkit.response import ApiError

SORT_WHITELIST = ("unit_price", "total_price", "area", "house_age", "house_id")
ORDER_WHITELIST = ("asc", "desc")
AREA_BANDS = ("lt60", "60-90", "90-120", "120-150", "150-180", "180-210", "gt210")
PREMIUM_METRICS = ("metro", "decoration", "structure")
CONTROLS = ("none", "district")


def path_int(ctx: Ctx, name: str = "id") -> int:
    """路径参数转整数；非法则 1001（不是 500）。"""
    try:
        return int(ctx.params[name])
    except (KeyError, TypeError, ValueError):
        raise ApiError(1001, f"路径参数 {name} 必须是整数")


def page(ctx: Ctx) -> tuple[int, int]:
    page_no = ctx.qi("page", 1, lo=1) or 1
    size = ctx.qi("page_size", 20, lo=1) or 20
    if size > 100:
        raise ApiError(1003, "page_size 不能超过 100")
    return page_no, size


def sort_order(ctx: Ctx) -> tuple[str, str]:
    sort = (ctx.qs("sort") or "unit_price").strip()
    order = (ctx.qs("order") or "asc").strip().lower()
    if sort not in SORT_WHITELIST:
        # 白名单校验：绝不把用户输入拼进 ORDER BY
        raise ApiError(1002, f"sort 只支持 {', '.join(SORT_WHITELIST)}")
    if order not in ORDER_WHITELIST:
        raise ApiError(1001, "order 只支持 asc / desc")
    return sort, order


def search(ctx: Ctx) -> dict:
    """把查询串解析成 repository.build_filter 需要的参数字典。"""
    price_min = ctx.qf("price_min")
    price_max = ctx.qf("price_max")
    area_min = ctx.qf("area_min")
    area_max = ctx.qf("area_max")
    if price_min is not None and price_max is not None and price_min > price_max:
        raise ApiError(1001, "price_min 不能大于 price_max")
    if area_min is not None and area_max is not None and area_min > area_max:
        raise ApiError(1001, "area_min 不能大于 area_max")

    keyword = ctx.qs("keyword")
    if keyword is not None and len(keyword) > 32:
        raise ApiError(1001, "keyword 长度不能超过 32")

    return {
        "keyword": keyword,
        "district_id": ctx.qi("district_id", lo=1),
        "street_id": ctx.qi("street_id", lo=1),
        "community_id": ctx.qi("community_id", lo=1),
        "price_min": price_min,
        "price_max": price_max,
        "area_min": area_min,
        "area_max": area_max,
        "room": ctx.qi("room", lo=1, hi=20),
        "hall": ctx.qi("hall", lo=0, hi=10),
        "age_max": ctx.qi("age_max", lo=0, hi=100),
        "decoration": ctx.qlist("decoration"),
        "structure": ctx.qlist("structure"),
        "direction": ctx.qlist("direction"),
        "near_subway": ctx.qi("near_subway", lo=0, hi=1),
        "include_outlier": ctx.qb("include_outlier", True),
    }


def distribution(ctx: Ctx) -> dict:
    metric = (ctx.qs("metric") or "total").strip()
    if metric not in ("total", "unit", "area"):
        raise ApiError(1001, "metric 只支持 total / unit / area")
    bins = ctx.qi("bins", 10, lo=3, hi=50) or 10
    binning = (ctx.qs("binning") or "quantile").strip()
    if binning not in ("quantile", "linear"):
        raise ApiError(1001, "binning 只支持 quantile / linear")
    return {"metric": metric, "bins": bins, "binning": binning,
            "district_id": ctx.qi("district_id", lo=1)}


def premium(ctx: Ctx) -> dict:
    metric = ctx.qs("metric")
    if metric not in PREMIUM_METRICS:
        raise ApiError(1001, f"metric 只支持 {', '.join(PREMIUM_METRICS)}")
    control = (ctx.qs("control") or "district").strip()
    if control not in CONTROLS:
        raise ApiError(1001, "control 只支持 none / district")
    stratify = ctx.qs("stratify")
    if stratify not in (None, "area_band"):
        raise ApiError(1001, "stratify 只支持 area_band")
    return {"metric": metric, "control": control,
            "base_group": ctx.qs("base_group"), "stratify": stratify}


def valuation(ctx: Ctx) -> dict:
    body = ctx.json()

    def need(name: str) -> float:
        if name not in body:
            raise ApiError(1001, f"缺少必填参数 {name}")
        try:
            return float(body[name])
        except (TypeError, ValueError):
            raise ApiError(1001, f"参数 {name} 必须是数字")

    area = need("area")
    if not (10 <= area <= 1000):
        raise ApiError(1001, "area 必须在 10–1000 之间")

    room = int(need("room"))
    if not (1 <= room <= 20):
        raise ApiError(1001, "room 必须在 1–20 之间")
    hall = int(need("hall"))
    if not (0 <= hall <= 10):
        raise ApiError(1001, "hall 必须在 0–10 之间")
    age = int(need("age"))
    if not (0 <= age <= 50):
        raise ApiError(1001, "age 必须在 0–50 之间")

    district_id = int(need("district_id"))
    street_id = body.get("street_id")
    street_id = int(street_id) if street_id not in (None, "") else None

    near_subway = body.get("near_subway")
    if near_subway is not None:
        near_subway = 1 if int(near_subway) else 0

    decoration = body.get("decoration")
    if decoration in ("", None):
        decoration = None
    floor_level = body.get("floor_level")
    if floor_level in ("", None):
        floor_level = None

    return {"district_id": district_id, "street_id": street_id, "area": area,
            "room": room, "hall": hall, "age": age, "decoration": decoration,
            "floor_level": floor_level, "near_subway": near_subway}


def auth_body(ctx: Ctx, *, for_register: bool = False) -> tuple[str, str]:
    """注册时校验密码强度（8–64）；登录时不校验强度，只要求非空——
    否则历史上用短密码创建的账号将永远无法登录。"""
    body = ctx.json()
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not (3 <= len(username) <= 32):
        raise ApiError(1001, "username 长度必须在 3–32 之间")
    if not password:
        raise ApiError(1001, "password 不能为空")
    if for_register and not (8 <= len(password) <= 64):
        raise ApiError(1001, "password 长度必须在 8–64 之间")
    if len(password) > 64:
        raise ApiError(1001, "password 长度不能超过 64")
    return username, password
