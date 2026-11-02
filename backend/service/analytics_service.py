"""分析看板聚合的业务规则与口径文案。"""

from __future__ import annotations

from ..core import db
from ..core.config import get as get_cfg
from ..dto import views
from ..httpkit.response import ApiError
from ..model.entities import District
from ..repository import analytics as arepo


def district_summary() -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        rows = arepo.district_summary(con)
    items = [views.district_item(District.from_row(r)) for r in rows]
    return {
        "list": items,
        "caliber": views.CALIBER_AVG,
        "note": "优先读取 district 聚合快照；快照与实时聚合的一致性由 db/load_sqlite.py 校验",
    }


def distribution(p: dict) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        body = arepo.price_distribution(con, p["metric"], p["district_id"],
                                        p["bins"], p["binning"])
    body["caliber"] = views.CALIBER_DIST
    return body


def scatter(district_id: int | None, limit: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        if district_id is not None:
            exists = con.execute("SELECT 1 FROM district WHERE id = ?",
                                 (int(district_id),)).fetchone()
            if not exists:
                raise ApiError(3001, f"区 {district_id} 不存在")
        body = arepo.area_price_scatter(con, district_id, limit)
    body["caliber"] = ("横轴面积、纵轴总价；pearson_r 由全量样本计算（不是抽样点）；"
                       "is_outlier=1 的点仅作标记，不剔除")
    return body


def age_trend(district_id: int | None) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        body = arepo.age_price_trend(con, district_id)
    body["caliber"] = views.CALIBER_AGE
    return body


def age_by_district(top_n: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        body = arepo.age_price_by_district(con, top_n)
    # n < 3 的点不输出（契约 §3.4）
    for s in body["series"]:
        s["points"] = [p for p in s["points"] if p["n"] >= views.SAMPLE_MIN]
    body["caliber"] = views.CALIBER_AGE
    body["why"] = ("全市口径下房龄与单价正相关是区位混杂造成的假象；"
                   "本接口提供分区对照，用于与 /analytics/age-price-trend 并排阅读")
    return body


def premium(p: dict) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        raw = arepo.premium(con, p["metric"], p["control"], p["base_group"], p["stratify"])
    base = raw["base_group"]
    return views.premium_result(raw, base_group=base)


def floor_orientation(metric: str) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        raw = arepo.floor_orientation(con)
    out: dict = {"caliber": views.CALIBER_ORIENT}
    if metric in ("floor", "both"):
        out["floor"] = views.mark_insufficient(raw["floor"])
    if metric in ("orientation", "both"):
        out["orientation"] = views.mark_insufficient(raw["orientation"])
        south = next((o for o in raw["orientation"] if o["direction"] == "南"), None)
        north = next((o for o in raw["orientation"] if o["direction"] == "北"), None)
        if south and north and north["avg_unit_price"]:
            out["orientation_spread"] = {
                "south_minus_north_pct": round(
                    (south["avg_unit_price"] - north["avg_unit_price"])
                    / north["avg_unit_price"] * 100, 2),
                "south_n": south["n"], "north_n": north["n"],
            }
    return out
