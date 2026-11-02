"""用户 / 收藏 / 批次 / 质量问题 / 导入写入 SQL。"""

from __future__ import annotations

import sqlite3

# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------
def user_by_username(con: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT u.id, u.username, u.password_hash, u.status, u.fail_count, u.lock_until, "
        "       u.last_login_at, r.code AS role "
        "  FROM app_user u JOIN role r ON r.id = u.role_id WHERE u.username = ?",
        (username,)
    ).fetchone()


def user_by_id(con: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT u.id, u.username, u.status, u.last_login_at, r.code AS role "
        "  FROM app_user u JOIN role r ON r.id = u.role_id WHERE u.id = ?", (int(user_id),)
    ).fetchone()


def role_id_by_code(con: sqlite3.Connection, code: str) -> int | None:
    row = con.execute("SELECT id FROM role WHERE code = ?", (code,)).fetchone()
    return int(row[0]) if row else None


def create_user(con: sqlite3.Connection, username: str, password_hash: str,
                role_id: int) -> int:
    cur = con.execute(
        "INSERT INTO app_user (username, password_hash, role_id, status) VALUES (?,?,?,1)",
        (username, password_hash, int(role_id))
    )
    return int(cur.lastrowid)


def update_login_fail(con: sqlite3.Connection, user_id: int, fail_count: int,
                      lock_until: str | None) -> None:
    con.execute("UPDATE app_user SET fail_count = ?, lock_until = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (int(fail_count), lock_until, int(user_id)))


def reset_login_fail(con: sqlite3.Connection, user_id: int) -> None:
    con.execute("UPDATE app_user SET fail_count = 0, lock_until = NULL, "
                "last_login_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (int(user_id),))


# ---------------------------------------------------------------------------
# 收藏
# ---------------------------------------------------------------------------
def favorite_exists(con: sqlite3.Connection, user_id: int, house_id: int) -> bool:
    return con.execute("SELECT 1 FROM favorite WHERE user_id = ? AND house_id = ?",
                       (int(user_id), int(house_id))).fetchone() is not None


def favorite_add(con: sqlite3.Connection, user_id: int, house_id: int) -> None:
    con.execute("INSERT OR IGNORE INTO favorite (user_id, house_id) VALUES (?,?)",
                (int(user_id), int(house_id)))


def favorite_remove(con: sqlite3.Connection, user_id: int, house_id: int) -> int:
    cur = con.execute("DELETE FROM favorite WHERE user_id = ? AND house_id = ?",
                      (int(user_id), int(house_id)))
    return int(cur.rowcount or 0)


def favorite_house_ids(con: sqlite3.Connection, user_id: int, limit: int,
                       offset: int) -> tuple[list[int], int]:
    total = int(con.execute("SELECT COUNT(*) FROM favorite WHERE user_id = ?",
                            (int(user_id),)).fetchone()[0])
    rows = con.execute(
        "SELECT house_id FROM favorite WHERE user_id = ? ORDER BY created_at DESC, id DESC "
        "LIMIT ? OFFSET ?", (int(user_id), int(limit), int(offset))
    ).fetchall()
    return [int(r[0]) for r in rows], total


# ---------------------------------------------------------------------------
# 操作日志
# ---------------------------------------------------------------------------
def log_operation(con: sqlite3.Connection, user_id: int | None, action: str,
                  target_type: str | None = None, target_id: str | None = None,
                  ip: str | None = None, result: str = "ok") -> None:
    con.execute(
        "INSERT INTO operation_log (user_id, action, target_type, target_id, ip, result) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, action, target_type, target_id, ip, result)
    )


def list_logs(con: sqlite3.Connection, action: str | None, limit: int,
              offset: int) -> tuple[list[sqlite3.Row], int]:
    where, args = "", []
    if action:
        where = " WHERE action = ?"
        args.append(action)
    total = int(con.execute(f"SELECT COUNT(*) FROM operation_log{where}", args).fetchone()[0])
    rows = con.execute(
        f"SELECT id, user_id, action, target_type, target_id, ip, result, created_at "
        f"  FROM operation_log{where} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*args, int(limit), int(offset)]
    ).fetchall()
    return rows, total


# ---------------------------------------------------------------------------
# 导入批次与质量问题
# ---------------------------------------------------------------------------
def batch_create(con: sqlite3.Connection, file_name: str, file_md5: str,
                 total_rows: int, status: str = "running",
                 operator_id: int | None = None) -> int:
    cur = con.execute(
        "INSERT INTO import_batch (file_name, file_md5, total_rows, loaded_rows, "
        "rejected_rows, status, operator_id) VALUES (?,?,?,0,0,?,?)",
        (file_name, file_md5, int(total_rows), status, operator_id)
    )
    return int(cur.lastrowid)


def batch_finish(con: sqlite3.Connection, batch_id: int, loaded: int, rejected: int,
                 status: str, duration_ms: int, note: str | None = None) -> None:
    con.execute(
        "UPDATE import_batch SET loaded_rows = ?, rejected_rows = ?, status = ?, "
        "duration_ms = ?, note = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE id = ?",
        (int(loaded), int(rejected), status, int(duration_ms), note, int(batch_id))
    )


def batch_by_id(con: sqlite3.Connection, batch_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM import_batch WHERE id = ?", (int(batch_id),)).fetchone()


def batch_list(con: sqlite3.Connection, limit: int, offset: int) -> tuple[list[sqlite3.Row], int]:
    total = int(con.execute("SELECT COUNT(*) FROM import_batch").fetchone()[0])
    rows = con.execute(
        "SELECT b.*, u.username AS operator FROM import_batch b "
        "  LEFT JOIN app_user u ON u.id = b.operator_id "
        " ORDER BY b.id DESC LIMIT ? OFFSET ?", (int(limit), int(offset))
    ).fetchall()
    return rows, total


def issues_insert_many(con: sqlite3.Connection, batch_id: int, issues: list[dict]) -> int:
    if not issues:
        return 0
    con.executemany(
        "INSERT INTO data_quality_issue (batch_id, rule_code, row_no, field_name, "
        "issue_type, raw_value, fixed_value) VALUES (?,?,?,?,?,?,?)",
        [(int(batch_id), i.get("rule"), i.get("row_no"), i.get("field"),
          i.get("issue_type"), i.get("raw_value"), i.get("fixed_value")) for i in issues]
    )
    return len(issues)


def rules_triggered(con: sqlite3.Connection, batch_id: int) -> dict[str, int]:
    rows = con.execute(
        "SELECT rule_code, COUNT(*) FROM data_quality_issue WHERE batch_id = ? "
        " GROUP BY rule_code ORDER BY rule_code", (int(batch_id),)
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def issues_by_batch(con: sqlite3.Connection, batch_id: int, limit: int) -> tuple[list[sqlite3.Row], int]:
    total = int(con.execute("SELECT COUNT(*) FROM data_quality_issue WHERE batch_id = ?",
                            (int(batch_id),)).fetchone()[0])
    rows = con.execute(
        "SELECT rule_code, row_no, field_name, issue_type, raw_value, fixed_value "
        "  FROM data_quality_issue WHERE batch_id = ? ORDER BY id LIMIT ?",
        (int(batch_id), int(limit))
    ).fetchall()
    return rows, total


def issues_by_type(con: sqlite3.Connection, batch_id: int) -> dict[str, int]:
    rows = con.execute(
        "SELECT rule_code || '|' || issue_type, COUNT(*) FROM data_quality_issue "
        " WHERE batch_id = ? GROUP BY 1 ORDER BY 1", (int(batch_id),)
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


# ---------------------------------------------------------------------------
# 导入写入
# ---------------------------------------------------------------------------
def district_upsert(con: sqlite3.Connection, name: str) -> int:
    row = con.execute("SELECT id FROM district WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row[0])
    return int(con.execute("INSERT INTO district (name) VALUES (?)", (name,)).lastrowid)


def street_upsert(con: sqlite3.Connection, district_id: int, name: str,
                  is_pseudo: int) -> int:
    row = con.execute("SELECT id FROM street WHERE district_id = ? AND name = ?",
                      (int(district_id), name)).fetchone()
    if row:
        return int(row[0])
    return int(con.execute(
        "INSERT INTO street (district_id, name, is_pseudo) VALUES (?,?,?)",
        (int(district_id), name, int(is_pseudo))).lastrowid)


def community_upsert(con: sqlite3.Connection, district_id: int, street_id: int,
                     name: str) -> int:
    row = con.execute("SELECT id FROM community WHERE district_id = ? AND name = ?",
                      (int(district_id), name)).fetchone()
    if row:
        return int(row[0])
    return int(con.execute(
        "INSERT INTO community (district_id, street_id, name) VALUES (?,?,?)",
        (int(district_id), int(street_id), name)).lastrowid)


HOUSE_INSERT_SQL = """
INSERT INTO house (district_id, street_id, community_id, batch_id, source_row_no,
                   room, hall, area, total_price, unit_price, floor_level, floor_total,
                   floor_raw, orientation_text, decoration, structure, house_age,
                   near_subway, is_outlier, abnormal_layout)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def houses_insert_many(con: sqlite3.Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    con.executemany(HOUSE_INSERT_SQL, rows)
    return len(rows)


def orientation_insert_many(con: sqlite3.Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    con.executemany(
        "INSERT OR IGNORE INTO house_orientation (house_id, direction) VALUES (?,?)", rows)
    return len(rows)


def _median(con: sqlite3.Connection, col: str, where: str, args: list) -> float | None:
    n = int(con.execute(f"SELECT COUNT(*) FROM house h WHERE {where}", args).fetchone()[0])
    if n == 0:
        return None
    off = (n - 1) // 2
    rows = con.execute(
        f"SELECT h.{col} FROM house h WHERE {where} AND h.{col} IS NOT NULL "
        f"ORDER BY h.{col} LIMIT 2 OFFSET ?", [*args, off]
    ).fetchall()
    if not rows:
        return None
    vals = [float(r[0]) for r in rows]
    med = vals[0] if (n % 2 or len(vals) == 1) else (vals[0] + vals[1]) / 2
    return round(med, 2)


def refresh_dim_aggregates(con: sqlite3.Connection) -> None:
    """导入后刷新三级维度的聚合快照（手册：聚合字段由任务刷新）。

    计数与均值用一条 UPDATE；中位数用逐维度计算后回写——SQLite 没有 median()，
    而把"取中间两值"的窗口逻辑写进一条 SQL 会难以审阅。
    """
    con.execute("""
        UPDATE district SET
          house_count    = (SELECT COUNT(*) FROM house h
                             WHERE h.district_id = district.id AND h.is_deleted = 0),
          avg_unit_price = (SELECT ROUND(AVG(unit_price), 2) FROM house h
                             WHERE h.district_id = district.id AND h.is_deleted = 0),
          avg_area       = (SELECT ROUND(AVG(area), 2) FROM house h
                             WHERE h.district_id = district.id AND h.is_deleted = 0),
          avg_age        = (SELECT ROUND(AVG(house_age), 2) FROM house h
                             WHERE h.district_id = district.id AND h.is_deleted = 0)
    """)
    con.execute("""
        UPDATE street SET
          house_count    = (SELECT COUNT(*) FROM house h
                             WHERE h.street_id = street.id AND h.is_deleted = 0),
          avg_unit_price = (SELECT ROUND(AVG(unit_price), 2) FROM house h
                             WHERE h.street_id = street.id AND h.is_deleted = 0)
    """)
    con.execute("""
        UPDATE community SET
          house_count    = (SELECT COUNT(*) FROM house h
                             WHERE h.community_id = community.id AND h.is_deleted = 0),
          avg_unit_price = (SELECT ROUND(AVG(unit_price), 2) FROM house h
                             WHERE h.community_id = community.id AND h.is_deleted = 0),
          avg_area       = (SELECT ROUND(AVG(area), 2) FROM house h
                             WHERE h.community_id = community.id AND h.is_deleted = 0),
          avg_age        = (SELECT ROUND(AVG(house_age), 2) FROM house h
                             WHERE h.community_id = community.id AND h.is_deleted = 0)
    """)

    for row in con.execute("SELECT id FROM district").fetchall():
        did = int(row[0])
        base = "h.district_id = ? AND h.is_deleted = 0"
        con.execute(
            "UPDATE district SET median_unit_price = ?, median_total_price = ? WHERE id = ?",
            (_median(con, "unit_price", base, [did]),
             _median(con, "total_price", base, [did]), did)
        )
    for row in con.execute("SELECT id FROM street").fetchall():
        sid = int(row[0])
        con.execute(
            "UPDATE street SET median_total_price = ? WHERE id = ?",
            (_median(con, "total_price", "h.street_id = ? AND h.is_deleted = 0", [sid]), sid)
        )
    for row in con.execute("SELECT id FROM community").fetchall():
        cid = int(row[0])
        con.execute(
            "UPDATE community SET median_total_price = ? WHERE id = ?",
            (_median(con, "total_price", "h.community_id = ? AND h.is_deleted = 0", [cid]), cid)
        )
