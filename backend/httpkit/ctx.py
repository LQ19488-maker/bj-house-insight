"""请求上下文：所有 handler 只接触 Ctx，不接触 HTTP 底层对象。

这样做的好处：把标准库 http.server 换成任何框架时，handler 一行不用改。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .response import ApiError


@dataclass
class Ctx:
    method: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    request_id: str = ""
    route_name: str = ""
    user: dict | None = None
    _json: dict | None = None

    # ---------------- 查询参数 ----------------
    def _raw(self, name: str) -> str | None:
        vals = self.query.get(name)
        return vals[-1] if vals else None

    def qs(self, name: str, default: str | None = None) -> str | None:
        v = self._raw(name)
        return default if v is None or v == "" else v

    def qi(self, name: str, default: int | None = None, *,
           lo: int | None = None, hi: int | None = None) -> int | None:
        v = self._raw(name)
        if v is None or v == "":
            return default
        try:
            n = int(v)
        except ValueError:
            raise ApiError(1001, f"参数 {name} 必须是整数")
        if lo is not None and n < lo:
            raise ApiError(1001, f"参数 {name} 不能小于 {lo}")
        if hi is not None and n > hi:
            raise ApiError(1001, f"参数 {name} 不能大于 {hi}")
        return n

    def qf(self, name: str, default: float | None = None) -> float | None:
        v = self._raw(name)
        if v is None or v == "":
            return default
        try:
            return float(v)
        except ValueError:
            raise ApiError(1001, f"参数 {name} 必须是数字")

    def qb(self, name: str, default: bool | None = None) -> bool | None:
        v = self._raw(name)
        if v is None or v == "":
            return default
        return v.strip().lower() in ("1", "true", "yes", "y", "on")

    def qlist(self, name: str) -> list[str]:
        """支持 ?direction=南,北 与 ?direction=南&direction=北 两种写法。"""
        vals = self.query.get(name) or []
        out: list[str] = []
        for v in vals:
            out.extend([x.strip() for x in v.split(",") if x.strip()])
        return out

    # ---------------- 请求体 ----------------
    def json(self) -> dict:
        if self._json is not None:
            return self._json
        if not self.body:
            self._json = {}
            return self._json
        ctype = (self.headers.get("content-type") or "").lower()
        if "application/json" not in ctype and self.body[:1] not in (b"{", b"["):
            raise ApiError(1001, "请求体必须是 application/json")
        try:
            self._json = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(1001, f"JSON 解析失败：{exc}")
        if not isinstance(self._json, dict):
            raise ApiError(1001, "请求体必须是 JSON 对象")
        return self._json

    # ---------------- 便捷 ----------------
    @property
    def is_admin(self) -> bool:
        return bool(self.user and self.user.get("role") == "admin")

    @property
    def user_id(self) -> int | None:
        return int(self.user["user_id"]) if self.user else None

    def require_login(self) -> dict:
        if not self.user:
            raise ApiError(2001)
        return self.user
