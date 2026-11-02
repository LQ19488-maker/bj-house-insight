"""注册 / 登录 / 当前用户 / 收藏。"""

from __future__ import annotations

import datetime as dt

from ..core import db
from ..core.config import get as get_cfg
from ..core.security import hash_password, sign_jwt, verify_password
from ..dto import views
from ..httpkit.response import ApiError
from ..model.entities import House
from ..repository import admin as admin_repo
from ..repository import house as house_repo

MAX_FAIL = 5
LOCK_MINUTES = 15


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def register(username: str, password: str) -> dict:
    cfg = get_cfg()
    if cfg.readonly:
        raise ApiError(5000, "当前为只读模式，注册已关闭")
    with db.transaction(cfg.db_path) as con:
        if admin_repo.user_by_username(con, username) is not None:
            raise ApiError(1001, f"用户名 {username} 已存在")
        role_id = admin_repo.role_id_by_code(con, "user")
        if role_id is None:
            raise ApiError(5000, "角色表缺少 user 角色")
        uid = admin_repo.create_user(con, username, hash_password(password), role_id)
        admin_repo.log_operation(con, uid, "register", "user", str(uid), None, "ok")
    return {"user_id": uid, "username": username, "role": "user"}


def _parse_lock(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def login(username: str, password: str) -> dict:
    cfg = get_cfg()
    with db.transaction(cfg.db_path) as con:
        row = admin_repo.user_by_username(con, username)
        if row is None:
            admin_repo.log_operation(con, None, "login", "user", username, None, "fail")
            raise ApiError(2001, "用户名或密码错误")

        lock_until = _parse_lock(row["lock_until"])
        if lock_until and lock_until > _now():
            raise ApiError(2004, f"账号已锁定，请于 {lock_until.isoformat(timespec='seconds')} 后重试",
                           detail={"lock_until": row["lock_until"]})

        if int(row["status"]) != 1:
            raise ApiError(2003, "账号已被禁用")

        if not verify_password(password, row["password_hash"]):
            fails = int(row["fail_count"] or 0) + 1
            lock_value = None
            if fails >= MAX_FAIL:
                lock_value = (_now() + dt.timedelta(minutes=LOCK_MINUTES)).isoformat(
                    timespec="seconds")
            admin_repo.update_login_fail(con, int(row["id"]), fails, lock_value)
            admin_repo.log_operation(con, int(row["id"]), "login", "user",
                                     username, None, "fail")
            if lock_value:
                raise ApiError(2004, f"连续失败 {MAX_FAIL} 次，账号锁定 {LOCK_MINUTES} 分钟",
                               detail={"lock_until": lock_value})
            raise ApiError(2001, f"用户名或密码错误（还可尝试 {MAX_FAIL - fails} 次）")

        admin_repo.reset_login_fail(con, int(row["id"]))
        admin_repo.log_operation(con, int(row["id"]), "login", "user", username, None, "ok")

        token = sign_jwt({"user_id": int(row["id"]), "role": row["role"]},
                         cfg.jwt_secret, cfg.jwt_ttl_seconds)
        user = {"user_id": int(row["id"]), "username": row["username"], "role": row["role"]}
    return {"token": token, "expires_in": cfg.jwt_ttl_seconds, "user": user}


def me(user_id: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        row = admin_repo.user_by_id(con, user_id)
    if row is None:
        raise ApiError(3001, "用户不存在")
    return {"user_id": int(row["id"]), "username": row["username"],
            "role": row["role"], "last_login_at": row["last_login_at"]}


# ---------------------------------------------------------------------------
# 收藏
# ---------------------------------------------------------------------------
def favorite_add(user_id: int, house_id: int) -> dict:
    cfg = get_cfg()
    if cfg.readonly:
        raise ApiError(5000, "当前为只读模式，收藏功能已关闭")
    with db.transaction(cfg.db_path) as con:
        if house_repo.get(con, house_id) is None:
            raise ApiError(3001, f"房源 {house_id} 不存在")
        already = admin_repo.favorite_exists(con, user_id, house_id)
        admin_repo.favorite_add(con, user_id, house_id)
        if not already:
            admin_repo.log_operation(con, user_id, "favorite", "house", str(house_id), None, "ok")
    return {"house_id": house_id, "favorited": True, "already": already}


def favorite_remove(user_id: int, house_id: int) -> dict:
    cfg = get_cfg()
    if cfg.readonly:
        raise ApiError(5000, "当前为只读模式，收藏功能已关闭")
    with db.transaction(cfg.db_path) as con:
        admin_repo.favorite_remove(con, user_id, house_id)
        admin_repo.log_operation(con, user_id, "unfavorite", "house", str(house_id), None, "ok")
    return {"house_id": house_id, "favorited": False}


def favorite_list(user_id: int, page_no: int, size: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        ids, total = admin_repo.favorite_house_ids(con, user_id, size, (page_no - 1) * size)
        rows = house_repo.by_ids(con, ids) if ids else []
        items = [views.card(House.from_row(r)) for r in rows]
    return views.page_result(items, total, page_no, size, 0.0)
