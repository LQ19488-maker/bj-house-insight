"""估价：相似房源加权均价的业务规则。

算法（契约 §3.6，必须逐条实现、不得自创）：
  1. 召回：同小区 → 面积 ±20% 且房龄 ±5 年
  2. 权重：w = 1/(1+面积差比) × 1/(1+房龄差/10)
  3. 估算单价：Σ(w×unit_price)/Σw；总价 = 单价 × area / 10000
  4. 区间：±8%
  5. 降级：样本 <5 降街道（medium）→ <3 降区（low）→ 0 条返回 insufficient_sample
"""

from __future__ import annotations

from ..core import db
from ..core.config import get as get_cfg
from ..httpkit.response import ApiError
from ..repository import dim as dim_repo
from ..repository import house as house_repo

AREA_PCT = 0.20
AGE_DIFF = 5
RANGE_PCT = 0.08
MIN_MEDIUM = 5
MIN_LOW = 3
MODEL_VERSION = "wa-1.0"
DISCLAIMER = "本结果基于相似房源加权均价，仅供参考，不构成评估报告"


def _recall(con, req: dict) -> tuple[list[tuple[float, float, int]], str]:
    """返回 [(unit_price, area, age)] 与降级层级。"""
    scopes = [
        ("community", "h.community_id = (SELECT community_id FROM house WHERE id = ?)", None),
    ]
    # 估价请求没有 house_id，因此按条件直接构造三层范围
    district_id = req["district_id"]
    street_id = req["street_id"]

    layers = []
    if street_id is not None:
        layers.append(("street", "h.street_id = ?", [int(street_id)]))
    layers.append(("district", "h.district_id = ?", [int(district_id), ]))

    best: list[tuple[float, float, int]] = []
    level = "none"

    for name, where, args in layers:
        sql = (
            "SELECT h.unit_price, h.area, h.house_age FROM house h "
            f" WHERE {where} AND h.is_deleted = 0 "
            "   AND h.area BETWEEN ? AND ? AND h.house_age BETWEEN ? AND ? "
            " LIMIT 400"
        )
        params = [*args,
                  float(req["area"]) * (1 - AREA_PCT), float(req["area"]) * (1 + AREA_PCT),
                  int(req["age"]) - AGE_DIFF, int(req["age"]) + AGE_DIFF]
        rows = con.execute(sql, params).fetchall()
        samples = [(float(r["unit_price"]), float(r["area"]), int(r["house_age"] or 0))
                   for r in rows]
        if samples:
            best, level = samples, name
        needed = MIN_LOW if name == "street" else MIN_MEDIUM
        if len(samples) >= needed:
            break

    return best, level


def estimate(req: dict, user_id: int | None = None) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        if dim_repo.district_by_id(con, req["district_id"]) is None:
            raise ApiError(3001, f"区 {req['district_id']} 不存在")
        if req["street_id"] is not None:
            st = dim_repo.street_by_id(con, req["street_id"])
            if st is None:
                raise ApiError(3001, f"街道 {req['street_id']} 不存在")
            if int(st["district_id"]) != int(req["district_id"]):
                raise ApiError(1001, "street_id 不属于所选的区")

        samples, level = _recall(con, req)

        if not samples:
            return {
                "est_unit_price": None, "est_total_price": None,
                "price_range": None, "sample_count": 0,
                "fallback_level": "none", "confidence": "low",
                "insufficient_sample": True,
                "disclaimer": DISCLAIMER, "model_version": MODEL_VERSION,
                "message": "同区同面积段无可用样本，无法给出参考价",
            }

        num = den = 0.0
        for unit_price, area, age in samples:
            area_ratio = abs(area - req["area"]) / req["area"]
            age_gap = abs(age - int(req["age"]))
            w = (1.0 / (1.0 + area_ratio)) * (1.0 / (1.0 + age_gap / 10.0))
            num += w * unit_price
            den += w
        est_unit = num / den if den else None
        if est_unit is None:
            raise ApiError(5000, "加权计算失败")

        est_total = est_unit * req["area"] / 10000.0
        n = len(samples)
        confidence = "high" if (n >= MIN_MEDIUM and level == "street") else "medium"
        if n < MIN_MEDIUM:
            confidence = "medium" if n >= MIN_LOW else "low"

        result = {
            "est_unit_price": round(est_unit, 2),
            "est_total_price": round(est_total, 2),
            "price_range": {
                "low": round(est_total * (1 - RANGE_PCT), 2),
                "high": round(est_total * (1 + RANGE_PCT), 2),
                "pct": int(RANGE_PCT * 100),
            },
            "sample_count": n,
            "fallback_level": level,
            "confidence": confidence,
            "insufficient_sample": n < MIN_LOW,
            "disclaimer": DISCLAIMER,
            "model_version": MODEL_VERSION,
            "caliber": ("权重 = 1/(1+面积差比) × 1/(1+房龄差/10)；"
                        "样本<5 强制低置信，<3 标记 insufficient_sample"),
        }

        _persist(con, req, result, user_id)
    return result


def _persist(con, req: dict, result: dict, user_id: int | None) -> None:
    """写 valuation_record；只读模式下跳过（不报错）。"""
    import json

    from ..repository import admin as admin_repo

    if get_cfg().readonly:
        return
    con.execute(
        "INSERT INTO valuation_record (user_id, input_json, est_unit_price, est_total_price, "
        "price_low, price_high, sample_count, fallback_level, confidence, model_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user_id, json.dumps(req, ensure_ascii=False), result["est_unit_price"],
         result["est_total_price"],
         None if result["price_range"] is None else result["price_range"]["low"],
         None if result["price_range"] is None else result["price_range"]["high"],
         result["sample_count"], result["fallback_level"], result["confidence"],
         MODEL_VERSION),
    )
    admin_repo.log_operation(con, user_id, "valuation", "house", None, None, "ok")
    con.commit()
