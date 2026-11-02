"""分析看板 / 小区画像 / 排行 SQL。

聚合全部写原生 SQL；只有"分位数与相关系数"这类需要遍历排序结果的，
才在取回数值后于本层做纯算术——不放业务判断（阈值、降级、口径文案都在 service）。
"""

from __future__ import annotations

import math
import sqlite3

AGE_BUCKETS = ["0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30-40", "40-50"]

AGE_BUCKET_SQL = """
CASE
  WHEN h.house_age <= 5  THEN '0-5'
  WHEN h.house_age <= 10 THEN '5-10'
  WHEN h.house_age <= 15 THEN '10-15'
  WHEN h.house_age <= 20 THEN '15-20'
  WHEN h.house_age <= 25 THEN '20-25'
  WHEN h.house_age <= 30 THEN '25-30'
  WHEN h.house_age <= 40 THEN '30-40'
  ELSE '40-50'
END
"""

AREA_BAND_SQL = """
CASE
  WHEN h.area < 60   THEN 'lt60'
  WHEN h.area < 90   THEN '60-90'
  WHEN h.area < 120  THEN '90-120'
  WHEN h.area < 150  THEN '120-150'
  WHEN h.area < 180  THEN '150-180'
  WHEN h.area < 210  THEN '180-210'
  ELSE 'gt210'
END
"""

METRIC_COL = {"total": "h.total_price", "unit": "h.unit_price", "area": "h.area"}


# ---------------------------------------------------------------------------
# 区级汇总
# ---------------------------------------------------------------------------
def district_summary(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT id AS district_id, name AS district_name, house_count, avg_unit_price, "
        "       median_unit_price, median_total_price, avg_area, avg_age "
        "  FROM district ORDER BY id"
    ).fetchall()


# ---------------------------------------------------------------------------
# 价格分布（分位分桶 / 等宽分桶）
# ---------------------------------------------------------------------------
def _values(con: sqlite3.Connection, col: str, district_id: int | None) -> list[float]:
    where, args = "h.is_deleted = 0", []
    if district_id is not None:
        where += " AND h.district_id = ?"
        args.append(int(district_id))
    rows = con.execute(
        f"SELECT {col} AS v FROM house h WHERE {where} AND {col} IS NOT NULL ORDER BY v", args
    ).fetchall()
    return [float(r[0]) for r in rows]


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def price_distribution(con: sqlite3.Connection, metric: str, district_id: int | None,
                       bins: int, binning: str) -> dict:
    col = METRIC_COL[metric]
    vals = _values(con, col, district_id)
    if not vals:
        return {"metric": metric, "binning": binning, "total": 0, "bins": [], "stats": {}}

    if binning == "quantile":
        edges = [_quantile(vals, i / bins) for i in range(bins + 1)]
    else:
        lo, hi = vals[0], vals[-1]
        step = (hi - lo) / bins if hi > lo else 1.0
        edges = [lo + step * i for i in range(bins)] + [hi]

    counts = [0] * bins
    for v in vals:
        for i in range(bins):
            last = i == bins - 1
            if (edges[i] <= v < edges[i + 1]) or (last and v == edges[i + 1]):
                counts[i] += 1
                break

    return {
        "metric": metric,
        "binning": binning,
        "total": len(vals),
        "bins": [{"low": round(edges[i], 2), "high": round(edges[i + 1], 2),
                  "count": counts[i]} for i in range(bins)],
        "stats": {
            "min": round(vals[0], 2),
            "p25": round(_quantile(vals, 0.25), 2),
            "median": round(_quantile(vals, 0.50), 2),
            "p75": round(_quantile(vals, 0.75), 2),
            "max": round(vals[-1], 2),
        },
    }


# ---------------------------------------------------------------------------
# 相关系数（用 SQL 聚合算，避免把全表拉到应用层）
# ---------------------------------------------------------------------------
def pearson(con: sqlite3.Connection, x: str, y: str,
            district_id: int | None = None) -> float | None:
    where, args = "is_deleted = 0", []
    if district_id is not None:
        where += " AND district_id = ?"
        args.append(int(district_id))
    row = con.execute(
        f"SELECT COUNT(*), SUM({x}), SUM({y}), SUM({x}*{y}), "
        f"       SUM({x}*{x}), SUM({y}*{y}) FROM house WHERE {where} "
        f"  AND {x} IS NOT NULL AND {y} IS NOT NULL", args
    ).fetchone()
    n = int(row[0] or 0)
    if n < 3:
        return None
    sx, sy, sxy, sxx, syy = (float(v or 0) for v in row[1:])
    denom = math.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy))
    if denom == 0:
        return None
    return round((n * sxy - sx * sy) / denom, 4)


# ---------------------------------------------------------------------------
# 面积-总价散点 + 回归
# ---------------------------------------------------------------------------
def area_price_scatter(con: sqlite3.Connection, district_id: int | None,
                       limit: int) -> dict:
    where, args = "h.is_deleted = 0", []
    if district_id is not None:
        where += " AND h.district_id = ?"
        args.append(int(district_id))
    rows = con.execute(
        f"SELECT h.id, h.area, h.total_price, h.is_outlier FROM house h "
        f" WHERE {where} ORDER BY h.id", args
    ).fetchall()

    n = len(rows)
    if n == 0:
        return {"points": [], "pearson_r": None, "n": 0, "regression": None}

    sx = sum(float(r["area"]) for r in rows)
    sy = sum(float(r["total_price"]) for r in rows)
    sxy = sum(float(r["area"]) * float(r["total_price"]) for r in rows)
    sxx = sum(float(r["area"]) ** 2 for r in rows)
    syy = sum(float(r["total_price"]) ** 2 for r in rows)
    denom = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / denom if denom else 0.0
    intercept = (sy - slope * sx) / n if n else 0.0
    r_denom = math.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy))
    r = round((n * sxy - sx * sy) / r_denom, 4) if r_denom else None

    step = max(1, n // int(limit)) if limit < n else 1
    picked = rows[::step][:limit]
    points = [{"x": round(float(r0["area"]), 2), "y": round(float(r0["total_price"]), 2),
               "is_outlier": int(r0["is_outlier"]), "house_id": int(r0["id"])}
              for r0 in picked]

    return {
        "points": points,
        "pearson_r": r,
        "n": n,
        "regression": {"slope": round(slope, 4), "intercept": round(intercept, 4)},
    }


# ---------------------------------------------------------------------------
# 房龄-单价：全市 / 分区
# ---------------------------------------------------------------------------
def age_price_trend(con: sqlite3.Connection, district_id: int | None = None) -> dict:
    where, args = "h.is_deleted = 0", []
    if district_id is not None:
        where += " AND h.district_id = ?"
        args.append(int(district_id))
    rows = con.execute(
        f"SELECT {AGE_BUCKET_SQL} AS bucket, COUNT(*) AS n, AVG(h.unit_price) AS avg "
        f"  FROM house h WHERE {where} GROUP BY bucket", args
    ).fetchall()
    by = {r["bucket"]: {"bucket": r["bucket"], "n": int(r["n"]),
                        "avg_unit_price": round(float(r["avg"]), 2)} for r in rows}
    buckets = [by[b] for b in AGE_BUCKETS if b in by]
    return {"buckets": buckets,
            "pearson_r": pearson(con, "house_age", "unit_price", district_id)}


def age_price_by_district(con: sqlite3.Connection, top_n: int) -> dict:
    tops = con.execute(
        "SELECT id, name FROM district ORDER BY house_count DESC, id LIMIT ?", (int(top_n),)
    ).fetchall()
    series = []
    for d in tops:
        rows = con.execute(
            f"SELECT {AGE_BUCKET_SQL} AS bucket, COUNT(*) AS n, AVG(h.unit_price) AS avg "
            "  FROM house h WHERE h.is_deleted = 0 AND h.district_id = ? GROUP BY bucket",
            (int(d["id"]),)
        ).fetchall()
        by = {r["bucket"]: {"bucket": r["bucket"], "n": int(r["n"]),
                            "avg_unit_price": round(float(r["avg"]), 2)} for r in rows}
        series.append({
            "district_id": int(d["id"]),
            "district_name": d["name"],
            "points": [by[b] for b in AGE_BUCKETS if b in by],
        })
    return {"buckets": AGE_BUCKETS, "series": series}


# ---------------------------------------------------------------------------
# 溢价（全市 / 同区控制 / 面积分层）
# ---------------------------------------------------------------------------
GROUP_EXPR = {
    "metro": "CASE WHEN h.near_subway = 1 THEN '近地铁' ELSE '不近地铁' END",
    "decoration": "h.decoration",
    "structure": "h.structure",
}

DEFAULT_BASE = {"metro": "不近地铁", "decoration": "简装", "structure": "板楼"}


def premium(con: sqlite3.Connection, metric: str, control: str, base_group: str | None,
            stratify: str | None = None) -> dict:
    expr = GROUP_EXPR[metric]
    base = base_group or DEFAULT_BASE[metric]

    rows = con.execute(
        f"SELECT {expr} AS grp, COUNT(*) AS n, AVG(h.unit_price) AS avg "
        "  FROM house h WHERE h.is_deleted = 0 AND h.decoration IS NOT NULL "
        f" GROUP BY grp ORDER BY n DESC"
    ).fetchall() if metric == "decoration" else con.execute(
        f"SELECT {expr} AS grp, COUNT(*) AS n, AVG(h.unit_price) AS avg "
        f"  FROM house h WHERE h.is_deleted = 0 GROUP BY grp ORDER BY n DESC"
    ).fetchall()

    groups = [{"group": r["grp"], "n": int(r["n"]), "avg_unit_price": round(float(r["avg"]), 2)}
              for r in rows]
    base_row = next((g for g in groups if g["group"] == base), None)
    base_avg = base_row["avg_unit_price"] if base_row else None
    for g in groups:
        g["premium_pct"] = (round((g["avg_unit_price"] - base_avg) / base_avg * 100, 2)
                            if base_avg else None)

    out = {"metric": metric, "control": control, "base_group": base, "groups": groups}

    if control == "district":
        by_d = []
        districts = con.execute(
            "SELECT id, name FROM district ORDER BY house_count DESC, id").fetchall()
        for d in districts:
            per = con.execute(
                f"SELECT {expr} AS grp, COUNT(*) AS n, AVG(h.unit_price) AS avg "
                "  FROM house h WHERE h.is_deleted = 0 AND h.district_id = ? GROUP BY grp",
                (int(d["id"]),)
            ).fetchall()
            got = {r["grp"]: (int(r["n"]), float(r["avg"])) for r in per}
            if base not in got:
                continue
            nb, ab = got[base]
            for grp, (nt, at) in got.items():
                if grp == base:
                    continue
                by_d.append({
                    "district_id": int(d["id"]), "district_name": d["name"],
                    "group": grp, "base_avg": round(ab, 2), "target_avg": round(at, 2),
                    "premium_pct": round((at - ab) / ab * 100, 2) if ab else None,
                    "n_base": nb, "n_target": nt,
                })
        out["by_district"] = by_d

    if stratify == "area_band":
        rows2 = con.execute(
            f"SELECT {AREA_BAND_SQL} AS band, {expr} AS grp, COUNT(*) AS n, "
            "       AVG(h.unit_price) AS avg "
            "  FROM house h WHERE h.is_deleted = 0 GROUP BY band, grp"
        ).fetchall()
        by_band: dict[str, list] = {}
        for r in rows2:
            by_band.setdefault(r["band"], []).append(
                {"group": r["grp"], "n": int(r["n"]), "avg_unit_price": round(float(r["avg"]), 2)})
        out["by_area_band"] = by_band

    return out


# ---------------------------------------------------------------------------
# 楼层与朝向
# ---------------------------------------------------------------------------
def floor_orientation(con: sqlite3.Connection) -> dict:
    floor = con.execute(
        "SELECT floor_level AS lvl, COUNT(*) AS n, AVG(unit_price) AS avg "
        "  FROM house WHERE is_deleted = 0 GROUP BY floor_level ORDER BY n DESC"
    ).fetchall()
    orient = con.execute(
        "SELECT o.direction AS dir, COUNT(*) AS n, AVG(h.unit_price) AS avg "
        "  FROM house h JOIN house_orientation o ON o.house_id = h.id "
        " WHERE h.is_deleted = 0 GROUP BY o.direction ORDER BY n DESC"
    ).fetchall()
    return {
        "floor": [{"level": r["lvl"], "n": int(r["n"]), "avg_unit_price": round(float(r["avg"]), 2)}
                  for r in floor],
        "orientation": [{"direction": r["dir"], "n": int(r["n"]),
                         "avg_unit_price": round(float(r["avg"]), 2)} for r in orient],
    }


# ---------------------------------------------------------------------------
# 小区画像与排行
# ---------------------------------------------------------------------------
def community_houses(con: sqlite3.Connection, community_id: int, limit: int = 50) -> list[sqlite3.Row]:
    from .house import CARD_SELECT
    return con.execute(
        f"{CARD_SELECT} WHERE h.community_id = ? AND h.is_deleted = 0 "
        "ORDER BY h.unit_price ASC LIMIT ?", (int(community_id), int(limit))
    ).fetchall()


def street_communities(con: sqlite3.Connection, street_id: int) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT id AS community_id, name AS community_name, house_count, "
        "       avg_unit_price, median_total_price "
        "  FROM community WHERE street_id = ? ORDER BY avg_unit_price DESC",
        (int(street_id),)
    ).fetchall()


def street_avg(con: sqlite3.Connection, street_id: int) -> tuple[float | None, int]:
    row = con.execute(
        "SELECT AVG(unit_price), COUNT(*) FROM house WHERE street_id = ? AND is_deleted = 0",
        (int(street_id),)
    ).fetchone()
    if not row or not row[1]:
        return None, 0
    return float(row[0]), int(row[1])


def rankings(con: sqlite3.Connection, scope: str, by: str, order: str,
             min_count: int, include_pseudo: bool, limit: int) -> list[sqlite3.Row]:
    direction = "DESC" if str(order).lower() == "desc" else "ASC"
    if scope == "street":
        pseudo = "" if include_pseudo else " AND s.is_pseudo = 0"
        return con.execute(
            "SELECT s.id AS id, s.name AS name, d.name AS district_name, s.house_count, "
            "       s.avg_unit_price, s.median_total_price, s.is_pseudo "
            "  FROM street s JOIN district d ON d.id = s.district_id "
            f" WHERE s.house_count >= ?{pseudo} "
            f" ORDER BY s.{by if by in ('avg_unit_price', 'house_count') else 'avg_unit_price'} "
            f"        {direction}, s.id LIMIT ?", (int(min_count), int(limit))
        ).fetchall()
    return con.execute(
        "SELECT c.id AS id, c.name AS name, d.name AS district_name, c.house_count, "
        "       c.avg_unit_price, c.median_total_price, 0 AS is_pseudo "
        "  FROM community c JOIN district d ON d.id = c.district_id "
        f" WHERE c.house_count >= ? "
        f" ORDER BY c.{by if by in ('avg_unit_price', 'house_count') else 'avg_unit_price'} "
        f"        {direction}, c.id LIMIT ?", (int(min_count), int(limit))
    ).fetchall()


def excluded_counts(con: sqlite3.Connection, min_count: int) -> dict:
    return {
        "excluded_by_min_count": int(con.execute(
            "SELECT COUNT(*) FROM community WHERE house_count < ?", (int(min_count),)
        ).fetchone()[0]),
        "excluded_pseudo": int(con.execute(
            "SELECT COUNT(*) FROM street WHERE is_pseudo = 1").fetchone()[0]),
    }
