"""房源检索 / 详情 / 相似 / 对比的业务规则。"""

from __future__ import annotations

import time

from ..core import db
from ..core.config import get as get_cfg
from ..dto import views
from ..httpkit.response import ApiError
from ..model.entities import Community, House, SimilarItem
from ..repository import house as house_repo

AREA_PCT = 0.20
AGE_DIFF = 5
FALLBACK_MIN = views.SAMPLE_MIN

DECORATION_SCORE = {"精装": 100, "简装": 66, "其他": 33, "毛坯": 0}


# ---------------------------------------------------------------------------
def search(params: dict, sort: str, order: str, page_no: int, size: int) -> dict:
    cfg = get_cfg()
    started = time.perf_counter()
    with db.session(cfg.db_path) as con:
        total = house_repo.count(con, params)
        rows = house_repo.search(con, params, size, (page_no - 1) * size, sort, order)
        items = [views.card(House.from_row(r)) for r in rows]
    return views.page_result(items, total, page_no, size,
                             (time.perf_counter() - started) * 1000)


# ---------------------------------------------------------------------------
def _recall(con, h: House, *, limit: int, min_needed: int) -> tuple[list[SimilarItem], str]:
    """同小区 → 同街道 → 同区 三级降级召回。

    降级阈值由调用方给出（详情页用 3，估价用 5），阈值属业务规则、放在 service。
    """
    scopes = [
        ("community", "h.community_id = ?", [h.community_id]),
        ("street", "h.street_id = ?", [h.street_id]),
        ("district", "h.district_id = ?", [h.district_id]),
    ]
    chosen: list = []
    level = "none"
    for name, where, args in scopes:
        rows = house_repo.similar_by_scope(
            con, h.house_id, where, args, h.area, h.house_age or 0, limit,
            area_pct=AREA_PCT, age_diff=AGE_DIFF)
        if rows:
            chosen, level = rows, name
        if len(rows) >= min_needed:
            break

    items = []
    for r in chosen:
        area = float(r["area"])
        age = int(r["house_age"] or 0)
        items.append(SimilarItem(
            house_id=int(r["house_id"]),
            community_name=r["community_name"],
            street_name=r["street_name"],
            area=area,
            total_price=float(r["total_price"]),
            unit_price=float(r["unit_price"]),
            house_age=age,
            match_level=level,
            area_diff_pct=(area - h.area) / h.area * 100 if h.area else 0.0,
            age_diff=age - (h.house_age or 0),
        ))
    return items, level


def similar(house_id: int, limit: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        row = house_repo.get(con, house_id)
        if row is None:
            raise ApiError(3001, f"房源 {house_id} 不存在")
        h = House.from_row(row)
        items, level = _recall(con, h, limit=limit, min_needed=FALLBACK_MIN)
    return {"house_id": h.house_id, "fallback_level": level,
            "sample_count": len(items), "list": [i.to_dict() for i in items]}


def detail(house_id: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        row = house_repo.get(con, house_id)
        if row is None:
            raise ApiError(3001, f"房源 {house_id} 不存在")
        h = House.from_row(row)
        h.directions = house_repo.directions(con, h.house_id)

        snap = house_repo.community_snapshot(con, h.community_id)
        community = None
        if snap is not None:
            community = Community(
                community_id=h.community_id, community_name=h.community_name,
                district_id=h.district_id, district_name=h.district_name,
                street_id=h.street_id, street_name=h.street_name,
                house_count=int(snap["house_count"]),
                avg_unit_price=None if snap["avg_unit_price"] is None else float(snap["avg_unit_price"]),
                median_total_price=(None if snap["median_total_price"] is None
                                    else float(snap["median_total_price"])),
                avg_area=None if snap["avg_area"] is None else float(snap["avg_area"]),
                avg_age=None if snap["avg_age"] is None else float(snap["avg_age"]),
            )

        stats = house_repo.district_unit_stats(con, h.district_id)
        percentile = None
        if stats["n"]:
            below = house_repo.count_below(con, h.district_id, h.unit_price)
            percentile = round(below / stats["n"] * 100, 1)

        items, _level = _recall(con, h, limit=5, min_needed=FALLBACK_MIN)
        raw = house_repo.get_raw(con, h.house_id)

    return views.detail(h, community=community, percentile=percentile,
                        district_n=stats["n"], p25=stats["p25"], p50=stats["p50"],
                        p75=stats["p75"], similar=items,
                        floor_raw=raw["floor_raw"], source_row_no=int(raw["source_row_no"]))


# ---------------------------------------------------------------------------
COMPARE_ATTRS = [
    ("unit_price", "单价(元/㎡)", True, "lower"),
    ("total_price", "总价(万元)", True, "lower"),
    ("area", "面积(㎡)", True, "higher"),
    ("layout", "户型", False, None),
    ("house_age", "房龄(年)", True, "lower"),
    ("decoration", "装修", False, None),
    ("structure", "结构", False, None),
    ("floor_level", "楼层", False, None),
    ("orientation_text", "朝向", False, None),
    ("near_subway", "近地铁", True, "higher"),
    ("is_outlier", "极值标记", False, None),
    ("abnormal_layout", "非常规户型", False, None),
]


def compare(ids: list[int]) -> dict:
    if not ids:
        raise ApiError(1001, "ids 不能为空")
    if len(ids) > 4:
        raise ApiError(1001, "最多只支持 4 套房源对比")

    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        rows = house_repo.by_ids(con, ids)
        if len(rows) != len(set(ids)):
            got = {int(r["house_id"]) for r in rows}
            raise ApiError(3001, f"房源不存在：{sorted(set(ids) - got)}")

        houses = [House.from_row(r) for r in rows]
        ranges = con.execute(
            "SELECT MIN(area), MAX(area), MIN(unit_price), MAX(unit_price), "
            "       MIN(house_age), MAX(house_age) FROM house WHERE is_deleted = 0"
        ).fetchone()

    def value_of(h: House, key: str):
        if key == "layout":
            return f"{h.room}室{h.hall}厅"
        return getattr(h, key)

    attributes = []
    for key, label, comparable, better in COMPARE_ATTRS:
        values = [value_of(h, key) for h in houses]
        diff = len({str(v) for v in values}) > 1
        best_index = None
        if comparable and diff:
            numeric = [float(v) for v in values]
            best_index = (numeric.index(min(numeric)) if better == "lower"
                          else numeric.index(max(numeric)))
        attributes.append({"key": key, "label": label, "values": values,
                           "diff": diff, "best_index": best_index})

    a_min, a_max, u_min, u_max, g_min, g_max = ranges

    def norm(v, lo, hi, higher_better=True):
        if hi is None or lo is None or hi == lo:
            return 0
        score = (float(v) - float(lo)) / (float(hi) - float(lo)) * 100
        score = max(0.0, min(100.0, score))
        return round(score if higher_better else 100 - score, 1)

    series = []
    for h in houses:
        series.append({
            "house_id": h.house_id,
            "scores": [
                norm(h.area, a_min, a_max, True),
                norm(h.unit_price, u_min, u_max, False),
                norm(h.house_age or 0, g_min, g_max, False),
                round(float(h.near_subway) * 100, 1),
                round(float(DECORATION_SCORE.get(h.decoration or "", 0)), 1),
            ],
        })

    return {
        "attributes": attributes,
        "radar": {
            "dimensions": ["面积", "单价", "房龄", "地铁", "装修"],
            "normalize_range": {"面积": [a_min, a_max], "单价": [u_min, u_max],
                                "房龄": [g_min, g_max],
                                "地铁": [0, 1], "装修": [0, 100]},
            "series": series,
            "note": "房龄与单价为“越低越好”，得分已反向；装修按 精装100/简装66/其他33/毛坯0 折算",
        },
    }


def anomaly(district_id: int | None, area_band: str, threshold: float, limit: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        if district_id is None:
            top = con.execute(
                "SELECT id FROM district ORDER BY house_count DESC, id LIMIT 1").fetchone()
            if top is None:
                raise ApiError(3001, "库中没有区数据")
            district_id = int(top[0])

        where = "h.district_id = ? AND h.is_deleted = 0 AND " + house_repo.AREA_BAND_SQL[area_band][0]
        median, n = house_repo.group_median_unit_price(con, where, [int(district_id)])
        if median is None:
            return {"group": {"district_id": district_id, "area_band": area_band,
                              "n": 0, "median_unit_price": None},
                    "list": [], "caliber": "同区+同面积段的中位单价为基准"}

        rows = house_repo.anomaly(con, district_id, area_band, median, threshold, limit)
        items = []
        for r in rows:
            h = House.from_row(r)
            body = views.card(h)
            body["deviation_pct"] = round((h.unit_price - median) / median * 100, 2)
            items.append(body)

        name = con.execute("SELECT name FROM district WHERE id = ?",
                           (int(district_id),)).fetchone()
    return {
        "group": {"district_id": int(district_id),
                  "district_name": name[0] if name else None,
                  "area_band": area_band, "n": n,
                  "median_unit_price": round(median, 2)},
        "threshold": threshold,
        "list": items,
        "caliber": "基准=同区+同面积段的单价中位数；deviation_pct 为相对基准的偏离百分比",
    }
