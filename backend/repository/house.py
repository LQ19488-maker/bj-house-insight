"""房源相关 SQL。只有 SQL 与参数绑定，不含任何业务判断。"""

from __future__ import annotations

import sqlite3

SORT_COLS = {
    "unit_price": "h.unit_price",
    "total_price": "h.total_price",
    "area": "h.area",
    "house_age": "h.house_age",
    "house_id": "h.id",
}

CARD_SELECT = """
SELECT h.id            AS house_id,
       h.district_id   AS district_id,
       d.name          AS district_name,
       h.street_id     AS street_id,
       s.name          AS street_name,
       h.community_id  AS community_id,
       c.name          AS community_name,
       h.room, h.hall, h.area, h.total_price, h.unit_price,
       h.floor_level, h.floor_total, h.house_age,
       h.decoration, h.structure, h.near_subway,
       h.orientation_text, h.is_outlier, h.abnormal_layout
  FROM house h
  JOIN district  d ON d.id = h.district_id
  JOIN street    s ON s.id = h.street_id
  JOIN community c ON c.id = h.community_id
"""


def build_filter(p: dict) -> tuple[str, list]:
    """检索条件构造器。**列表查询与 COUNT 必须共用本函数**，
    否则会出现"共 N 条但翻到第 2 页就空"的经典 bug。"""
    clauses = ["h.is_deleted = 0"]
    args: list = []

    if p.get("keyword"):
        clauses.append("c.name LIKE ?")
        args.append(str(p["keyword"]) + "%")
    for key, col in (("district_id", "h.district_id"), ("street_id", "h.street_id"),
                     ("community_id", "h.community_id")):
        if p.get(key) is not None:
            clauses.append(f"{col} = ?")
            args.append(int(p[key]))
    if p.get("price_min") is not None:
        clauses.append("h.total_price >= ?")
        args.append(float(p["price_min"]))
    if p.get("price_max") is not None:
        clauses.append("h.total_price <= ?")
        args.append(float(p["price_max"]))
    if p.get("area_min") is not None:
        clauses.append("h.area >= ?")
        args.append(float(p["area_min"]))
    if p.get("area_max") is not None:
        clauses.append("h.area <= ?")
        args.append(float(p["area_max"]))
    if p.get("room") is not None:
        clauses.append("h.room = ?")
        args.append(int(p["room"]))
    if p.get("hall") is not None:
        clauses.append("h.hall = ?")
        args.append(int(p["hall"]))
    if p.get("age_max") is not None:
        clauses.append("h.house_age <= ?")
        args.append(int(p["age_max"]))
    for key, col in (("decoration", "h.decoration"), ("structure", "h.structure")):
        values = p.get(key) or []
        if values:
            clauses.append(f"{col} IN ({','.join('?' * len(values))})")
            args.extend(values)
    if p.get("near_subway") is not None:
        clauses.append("h.near_subway = ?")
        args.append(int(p["near_subway"]))
    if p.get("direction"):
        values = p["direction"]
        clauses.append(
            "EXISTS (SELECT 1 FROM house_orientation o "
            f"WHERE o.house_id = h.id AND o.direction IN ({','.join('?' * len(values))}))"
        )
        args.extend(values)
    if p.get("include_outlier") is False:
        clauses.append("h.is_outlier = 0")

    return " AND ".join(clauses), args


def count(con: sqlite3.Connection, p: dict) -> int:
    where, args = build_filter(p)
    sql = ("SELECT COUNT(*) FROM house h "
           "JOIN community c ON c.id = h.community_id "
           f"WHERE {where}")
    return int(con.execute(sql, args).fetchone()[0])


def search(con: sqlite3.Connection, p: dict, limit: int, offset: int,
           sort: str = "unit_price", order: str = "asc") -> list[sqlite3.Row]:
    where, args = build_filter(p)
    col = SORT_COLS.get(sort, "h.unit_price")
    direction = "DESC" if str(order).lower() == "desc" else "ASC"
    sql = (f"{CARD_SELECT} WHERE {where} "
           f"ORDER BY {col} {direction}, h.id ASC LIMIT ? OFFSET ?")
    return con.execute(sql, [*args, int(limit), int(offset)]).fetchall()


def get(con: sqlite3.Connection, house_id: int) -> sqlite3.Row | None:
    sql = CARD_SELECT + " WHERE h.id = ?"
    return con.execute(sql, (int(house_id),)).fetchone()


def get_raw(con: sqlite3.Connection, house_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM house WHERE id = ?", (int(house_id),)).fetchone()


def directions(con: sqlite3.Connection, house_id: int) -> list[str]:
    rows = con.execute(
        "SELECT direction FROM house_orientation WHERE house_id = ? "
        "ORDER BY CASE direction WHEN '东南' THEN 1 WHEN '东北' THEN 2 "
        "WHEN '西南' THEN 3 WHEN '西北' THEN 4 WHEN '东' THEN 5 "
        "WHEN '南' THEN 6 WHEN '西' THEN 7 ELSE 8 END", (int(house_id),)
    ).fetchall()
    return [r[0] for r in rows]


def community_snapshot(con: sqlite3.Connection, community_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT house_count, avg_unit_price, median_total_price, avg_area, avg_age "
        "FROM community WHERE id = ?", (int(community_id),)
    ).fetchone()


def district_unit_stats(con: sqlite3.Connection, district_id: int) -> dict:
    """同区单价分布：用于"这套房在本区什么位置"。"""
    n = int(con.execute("SELECT COUNT(*) FROM house WHERE district_id = ? AND is_deleted = 0",
                        (int(district_id),)).fetchone()[0])
    if n == 0:
        return {"n": 0, "percentile": None, "p25": None, "p50": None, "p75": None}

    def pct(q: float):
        off = int(round((n - 1) * q))
        return con.execute(
            "SELECT unit_price FROM house WHERE district_id = ? AND is_deleted = 0 "
            "ORDER BY unit_price LIMIT 1 OFFSET ?", (int(district_id), off)
        ).fetchone()[0]

    return {"n": n, "p25": pct(0.25), "p50": pct(0.50), "p75": pct(0.75)}


def count_below(con: sqlite3.Connection, district_id: int, unit_price: float) -> int:
    return int(con.execute(
        "SELECT COUNT(*) FROM house WHERE district_id = ? AND is_deleted = 0 AND unit_price < ?",
        (int(district_id), float(unit_price))).fetchone()[0])


SIMILAR_SELECT = """
SELECT h.id AS house_id, c.name AS community_name, s.name AS street_name,
       h.area, h.total_price, h.unit_price, h.house_age, h.decoration
  FROM house h
  JOIN community c ON c.id = h.community_id
  JOIN street    s ON s.id = h.street_id
 WHERE h.id <> ? AND h.is_deleted = 0 AND {scope}
 ORDER BY ABS(h.area - ?) ASC, ABS(h.house_age - ?) ASC
 LIMIT ?
"""


def similar_by_scope(con: sqlite3.Connection, house_id: int, scope_sql: str,
                     scope_args: list, area: float, age: int, limit: int,
                     *, area_pct: float, age_diff: int) -> list[sqlite3.Row]:
    """按范围召回相似房源；scope_sql 由 service 决定（同小区/同街道/同区）。"""
    sql = SIMILAR_SELECT.format(scope=scope_sql)
    args = [int(house_id), *scope_args, float(area), int(age), int(limit)]
    rows = con.execute(sql, args).fetchall()
    return [r for r in rows
            if abs(r["area"] - area) <= area * area_pct and abs(r["house_age"] - age) <= age_diff]


def by_ids(con: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    sql = CARD_SELECT + f" WHERE h.id IN ({','.join('?' * len(ids))})"
    rows = con.execute(sql, ids).fetchall()
    order = {int(v): i for i, v in enumerate(ids)}
    return sorted(rows, key=lambda r: order.get(int(r["house_id"]), 999))


AREA_BAND_SQL = {
    "lt60": ("h.area < 60", []),
    "60-90": ("h.area >= 60 AND h.area < 90", []),
    "90-120": ("h.area >= 90 AND h.area < 120", []),
    "120-150": ("h.area >= 120 AND h.area < 150", []),
    "150-180": ("h.area >= 150 AND h.area < 180", []),
    "180-210": ("h.area >= 180 AND h.area < 210", []),
    "gt210": ("h.area >= 210", []),
}


def group_median_unit_price(con: sqlite3.Connection, where: str, args: list) -> tuple[float | None, int]:
    n = int(con.execute(f"SELECT COUNT(*) FROM house h WHERE {where}", args).fetchone()[0])
    if n == 0:
        return None, 0
    off = (n - 1) // 2
    rows = con.execute(
        f"SELECT h.unit_price FROM house h WHERE {where} ORDER BY h.unit_price "
        f"LIMIT 2 OFFSET ?", [*args, off]
    ).fetchall()
    med = rows[0][0] if n % 2 else (rows[0][0] + rows[1][0]) / 2
    return float(med), n


def anomaly(con: sqlite3.Connection, district_id: int, area_band: str,
            median: float, threshold: float, limit: int) -> list[sqlite3.Row]:
    band_sql, band_args = AREA_BAND_SQL[area_band]
    sql = CARD_SELECT + (
        f" WHERE h.district_id = ? AND h.is_deleted = 0 AND ({band_sql})"
        "   AND h.unit_price <= ?"
        " ORDER BY h.unit_price ASC LIMIT ?"
    )
    args = [int(district_id), *band_args, float(median) * (1 - float(threshold)), int(limit)]
    return con.execute(sql, args).fetchall()
