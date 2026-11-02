"""维度表与筛选项 SQL。"""

from __future__ import annotations

import sqlite3


def districts(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT id AS district_id, name AS district_name, house_count, "
        "       avg_unit_price, median_unit_price, median_total_price, avg_area, avg_age "
        "  FROM district ORDER BY id"
    ).fetchall()


def district_by_id(con: sqlite3.Connection, district_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT id, name FROM district WHERE id = ?",
                       (int(district_id),)).fetchone()


def streets(con: sqlite3.Connection, district_id: int | None,
            include_pseudo: bool) -> list[sqlite3.Row]:
    clauses, args = [], []
    if district_id is not None:
        clauses.append("district_id = ?")
        args.append(int(district_id))
    if not include_pseudo:
        clauses.append("is_pseudo = 0")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return con.execute(
        "SELECT id AS street_id, district_id, name AS street_name, is_pseudo, house_count "
        f"  FROM street{where} ORDER BY district_id, id", args
    ).fetchall()


def street_by_id(con: sqlite3.Connection, street_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT id, district_id, name FROM street WHERE id = ?",
                       (int(street_id),)).fetchone()


def community_by_id(con: sqlite3.Connection, community_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT c.id, c.name, c.district_id, c.street_id, c.house_count, c.avg_unit_price, "
        "       c.median_total_price, c.avg_area, c.avg_age, d.name AS district_name, "
        "       s.name AS street_name "
        "  FROM community c JOIN district d ON d.id = c.district_id "
        "  JOIN street s ON s.id = c.street_id WHERE c.id = ?", (int(community_id),)
    ).fetchone()


def filters(con: sqlite3.Connection) -> dict:
    def distinct(col: str, table: str = "house") -> list[str]:
        rows = con.execute(
            f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL ORDER BY {col}"
        ).fetchall()
        return [r[0] for r in rows]

    rng = con.execute(
        "SELECT MIN(total_price), MAX(total_price), MIN(area), MAX(area), "
        "       MIN(house_age), MAX(house_age), MIN(room), MAX(room), MIN(hall), MAX(hall) "
        "  FROM house WHERE is_deleted = 0"
    ).fetchone()

    return {
        "decoration": ["精装", "简装", "其他", "毛坯"],
        "structure": ["板楼", "塔楼", "板塔结合", "独栋别墅", "平房"],
        "direction": ["东", "南", "西", "北", "东北", "东南", "西南", "西北"],
        "floor_level": ["低", "中", "高", "顶层", "底层", "地下", "上叠", "未知"],
        "ranges": {
            "total_price": [rng[0], rng[1]],
            "area": [rng[2], rng[3]],
            "house_age": [rng[4], rng[5]],
            "room": [rng[6], rng[7]],
            "hall": [rng[8], rng[9]],
        },
    }
