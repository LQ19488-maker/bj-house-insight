"""响应构造：实体 → 契约字段名。

**契约字段名只在这里出现一次**，前端对接与 `docs/api-contract.md` 比对时只需看本文件。
"""

from __future__ import annotations

from ..model.entities import Community, District, House, SimilarItem, Street

# 计算任何分组均价时的最小样本量（契约 §0.4，threshold 属业务规则）
SAMPLE_MIN = 3

CALIBER_AVG = "算术均值；n<3 的分组不参与计算并置 insufficient_sample=true"
CALIBER_PREMIUM = "算术均值；溢价率 =(组均价-基准组均价)/基准组均价×100，保留 2 位；n<3 不参与计算"
CALIBER_AGE = "分区后各房龄段的算术均价；n<3 的点不输出；房龄以 2024 为基准年"
CALIBER_ORIENT = "朝向经 house_orientation 展开为 M:N 后按方向聚合；楼层层级“未知”单独成组"
CALIBER_DIST = "分位分桶（等宽分桶会把多数样本挤进第一桶）"


def card(h: House) -> dict:
    return {
        "house_id": h.house_id,
        "district_id": h.district_id,
        "district_name": h.district_name,
        "street_id": h.street_id,
        "street_name": h.street_name,
        "community_id": h.community_id,
        "community_name": h.community_name,
        "room": h.room,
        "hall": h.hall,
        "area": h.area,
        "total_price": h.total_price,
        "unit_price": h.unit_price,
        "floor_level": h.floor_level,
        "floor_total": h.floor_total,
        "house_age": h.house_age,
        "decoration": h.decoration,
        "structure": h.structure,
        "near_subway": h.near_subway,
        "orientation_text": h.orientation_text,
        "is_outlier": h.is_outlier,
        "abnormal_layout": h.abnormal_layout,
    }


def page_result(items: list, total: int, page_no: int, size: int, took_ms: float) -> dict:
    return {"list": items, "total": int(total), "page": int(page_no),
            "page_size": int(size), "took_ms": round(took_ms, 1)}


def detail(h: House, *, community: Community | None, percentile: float | None,
           district_n: int, p25: float | None, p50: float | None, p75: float | None,
           similar: list[SimilarItem], floor_raw: str | None, source_row_no: int) -> dict:
    body = card(h)
    body.update({
        "directions": h.directions,
        "floor_raw": floor_raw,
        "source_row_no": source_row_no,
        "community": None if community is None else {
            "house_count": community.house_count,
            "avg_unit_price": community.avg_unit_price,
            "median_total_price": community.median_total_price,
            "avg_area": community.avg_area,
            "avg_age": community.avg_age,
        },
        "district_percentile": percentile,
        "district_sample_size": district_n,
        "district_quantiles": {"p25": p25, "p50": p50, "p75": p75},
        "similar": [s.to_dict() for s in similar],
    })
    return body


def district_item(d: District) -> dict:
    return {
        "district_id": d.district_id,
        "district_name": d.district_name,
        "house_count": d.house_count,
        "avg_unit_price": d.avg_unit_price,
        "median_unit_price": d.median_unit_price,
        "median_total_price": d.median_total_price,
        "avg_area": d.avg_area,
        "avg_age": d.avg_age,
        "insufficient_sample": d.house_count < SAMPLE_MIN,
    }


def street_item(s: Street) -> dict:
    return {"street_id": s.street_id, "district_id": s.district_id,
            "street_name": s.street_name, "is_pseudo": s.is_pseudo,
            "house_count": s.house_count}


def community_item(c: Community) -> dict:
    return {
        "community_id": c.community_id, "community_name": c.community_name,
        "district_id": c.district_id, "district_name": c.district_name,
        "street_id": c.street_id, "street_name": c.street_name,
        "house_count": c.house_count, "avg_unit_price": c.avg_unit_price,
        "median_total_price": c.median_total_price,
        "avg_area": c.avg_area, "avg_age": c.avg_age,
    }


def mark_insufficient(groups: list[dict], key: str = "n") -> list[dict]:
    for g in groups:
        g["insufficient_sample"] = int(g.get(key) or 0) < SAMPLE_MIN
    return groups


def premium_result(raw: dict, *, base_group: str) -> dict:
    groups = mark_insufficient(raw["groups"])
    out = {
        "metric": raw["metric"],
        "control": raw["control"],
        "base_group": base_group,
        "groups": groups,
        "caliber": CALIBER_PREMIUM,
    }
    if "by_district" in raw:
        out["by_district"] = [
            {**item, "insufficient_sample": (item["n_base"] < SAMPLE_MIN
                                             or item["n_target"] < SAMPLE_MIN)}
            for item in raw["by_district"]
        ]
    if "by_area_band" in raw:
        out["by_area_band"] = {
            band: mark_insufficient(items) for band, items in raw["by_area_band"].items()
        }
    return out


def ranking_item(row) -> dict:
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "district_name": row["district_name"],
        "house_count": int(row["house_count"]),
        "avg_unit_price": None if row["avg_unit_price"] is None else round(float(row["avg_unit_price"]), 2),
        "median_total_price": (None if row["median_total_price"] is None
                               else round(float(row["median_total_price"]), 2)),
        "is_pseudo": int(row["is_pseudo"]) if "is_pseudo" in row.keys() else 0,
    }
