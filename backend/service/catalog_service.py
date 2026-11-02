"""维度字典 / 小区画像 / 排行的业务规则。"""

from __future__ import annotations

from ..core import db
from ..core.config import get as get_cfg
from ..dto import views
from ..httpkit.response import ApiError
from ..model.entities import Community, House, Street
from ..repository import analytics as arepo
from ..repository import dim as dim_repo
from ..repository import house as house_repo


def districts() -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        rows = dim_repo.districts(con)
    return {"list": [{"district_id": int(r["district_id"]),
                      "district_name": r["district_name"],
                      "house_count": int(r["house_count"])} for r in rows]}


def streets(district_id: int | None, include_pseudo: bool) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        if district_id is not None and dim_repo.district_by_id(con, district_id) is None:
            raise ApiError(3001, f"区 {district_id} 不存在")
        rows = dim_repo.streets(con, district_id, include_pseudo)
    return {"list": [views.street_item(Street.from_row(r)) for r in rows],
            "include_pseudo": include_pseudo}


def filters() -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        return dim_repo.filters(con)


def community(community_id: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        row = dim_repo.community_by_id(con, community_id)
        if row is None:
            raise ApiError(3001, f"小区 {community_id} 不存在")
        c = Community.from_row(row)

        houses = [views.card(House.from_row(r))
                  for r in arepo.community_houses(con, community_id)]
        street_avg, street_n = arepo.street_avg(con, c.street_id)
        peers = arepo.street_communities(con, c.street_id)

        percentile = None
        if street_avg and c.avg_unit_price:
            lower = sum(1 for p in peers
                        if (p["avg_unit_price"] or 0) < (c.avg_unit_price or 0))
            percentile = round(lower / len(peers) * 100, 1) if peers else None

    return {
        **views.community_item(c),
        "street_percentile": percentile,
        "street_community_count": len(peers),
        "street_avg_unit_price": None if street_avg is None else round(street_avg, 2),
        "street_house_count": street_n,
        "houses": houses,
        "street_rank": [
            {
                "community_id": int(p["community_id"]),
                "community_name": p["community_name"],
                "house_count": int(p["house_count"]),
                "avg_unit_price": (None if p["avg_unit_price"] is None
                                   else round(float(p["avg_unit_price"]), 2)),
                "median_total_price": (None if p["median_total_price"] is None
                                       else round(float(p["median_total_price"]), 2)),
            }
            for p in peers
        ],
        "note": ("67.4% 的小区只有 1 套在售，因此本接口只提供"
                 "“在同街道中的位置”，不提供小区内价格波动分析"),
    }


def rankings(scope: str, by: str, order: str, min_count: int,
             include_pseudo: bool, limit: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        rows = arepo.rankings(con, scope, by, order, min_count, include_pseudo, limit)
        excluded = arepo.excluded_counts(con, min_count)
    return {
        "scope": scope,
        "list": [views.ranking_item(r) for r in rows],
        "excluded_by_min_count": excluded["excluded_by_min_count"],
        "excluded_pseudo": excluded["excluded_pseudo"],
        "caliber": f"仅统计 house_count >= {min_count} 的条目；街道排行默认排除 is_pseudo=1 的伪街道",
    }
