"""数据库连接与初始化。

三个必须记住的 SQLite 细节（都写进 ADR §2 的让步代价里）：
  1. `PRAGMA foreign_keys = ON` —— SQLite 默认**不校验外键**，不显式打开等于没建约束
  2. `journal_mode = WAL` —— 读写不互相阻塞，避免接口并发时 database is locked
  3. `busy_timeout = 5000` —— 短暂锁冲突时等待而不是立刻报错
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..httpkit.response import ApiError

DEMO_USERS = [
    ("admin", "admin1234", "admin"),
    ("user", "user1234", "user"),
]


def connect(db_path: Path) -> sqlite3.Connection:
    if not Path(db_path).exists():
        raise ApiError(5000, f"数据库不存在：{db_path}，请先运行 run-etl.cmd --db")
    con = sqlite3.connect(str(db_path), timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


@contextmanager
def session(db_path: Path):
    """每请求一个连接（ThreadingHTTPServer 是多线程，连接不能跨线程共享）。"""
    con = connect(db_path)
    try:
        yield con
    finally:
        con.close()


@contextmanager
def transaction(db_path: Path):
    con = connect(db_path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def health(db_path: Path) -> dict:
    """给 /health 用：返回库状态、房源规模与两个均价口径。

    把均价口径放进 /health，是为了让首页 KPI 只有一个来源——
    否则前端会拿区级汇总再算一遍，口径必然分叉。
    """
    try:
        with session(db_path) as con:
            row = con.execute(
                "SELECT COUNT(*) AS n, AVG(unit_price) AS avg_u, "
                "       SUM(total_price * 10000.0) / SUM(area) AS weighted_u "
                "  FROM house WHERE is_deleted = 0"
            ).fetchone()
            districts = con.execute("SELECT COUNT(*) FROM district").fetchone()[0]
            communities = con.execute("SELECT COUNT(*) FROM community").fetchone()[0]
            n = int(row["n"])
            mid = con.execute(
                "SELECT total_price FROM house WHERE is_deleted = 0 "
                " ORDER BY total_price LIMIT 2 OFFSET ?", (max(0, (n - 1) // 2),)
            ).fetchall()
        median_total = None
        if mid:
            vals = [float(r[0]) for r in mid]
            median_total = round(vals[0] if len(vals) == 1 else (vals[0] + vals[1]) / 2, 2)
        return {
            "db": "up",
            "house_rows": n,
            "districts": int(districts),
            "communities": int(communities),
            "avg_unit_price": round(float(row["avg_u"] or 0), 2),
            "weighted_unit_price": round(float(row["weighted_u"] or 0), 2),
            "median_total_price": median_total,
        }
    except Exception as exc:  # pragma: no cover - 仅在库损坏时触发
        return {"db": "down", "error": str(exc)}


def ensure_demo_users(db_path: Path) -> list[str]:
    """首次启动时创建演示账号；已存在但密码不符时重置为演示密码。

    重置只针对下面两个固定用户名，且每次启动都会在日志里提示，
    避免"不知情地被改密码"。演示账号密码均为 8 位，满足注册的强度校验。
    """
    from .security import hash_password, verify_password

    created: list[str] = []
    with transaction(db_path) as con:
        roles = {r["code"]: r["id"] for r in con.execute("SELECT id, code FROM role")}
        for username, password, role_code in DEMO_USERS:
            row = con.execute(
                "SELECT id, password_hash FROM app_user WHERE username = ?", (username,)
            ).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO app_user (username, password_hash, role_id, status) "
                    "VALUES (?, ?, ?, 1)",
                    (username, hash_password(password), roles.get(role_code, 2)),
                )
                created.append(username)
            elif not verify_password(password, row["password_hash"]):
                con.execute(
                    "UPDATE app_user SET password_hash = ?, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                    (hash_password(password), int(row["id"])),
                )
                created.append(f"{username}(重置密码)")
    return created
