"""极简路由：正则匹配 + 路径参数 + 鉴权标注。

路由表是唯一的路由事实源，`tools/check_contract.py` 会解析它来和接口契约比对。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .ctx import Ctx

# 鉴权级别
PUBLIC = "public"      # 完全公开
OPTIONAL = "optional"  # 有 token 就解析，没有也放行
LOGIN = "login"        # 必须登录
ADMIN = "admin"        # 必须是管理员


@dataclass
class Route:
    method: str
    pattern: str            # 如 /houses/{id}
    regex: re.Pattern
    handler: Callable[[Ctx], object]
    name: str
    auth: str = PUBLIC

    def match(self, path: str) -> dict | None:
        m = self.regex.fullmatch(path)
        return m.groupdict() if m else None


def _compile(pattern: str) -> re.Pattern:
    # /houses/{id} → /houses/(?P<id>[^/]+)
    expr = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
    return re.compile(expr)


class Router:
    def __init__(self) -> None:
        self.routes: list[Route] = []

    def add(self, method: str, pattern: str, handler, *, name: str,
            auth: str = PUBLIC) -> None:
        self.routes.append(Route(method.upper(), pattern, _compile(pattern),
                                 handler, name, auth))

    def match(self, method: str, path: str):
        """返回 (route, params)；路径存在但方法不对时抛 1001 之外的 404。"""
        path_matched = False
        for r in self.routes:
            params = r.match(path)
            if params is None:
                continue
            path_matched = True
            if r.method == method.upper():
                return r, params
        return (None, {"__path_matched__": path_matched})

    def describe(self) -> list[dict]:
        return [{"method": r.method, "path": r.pattern, "name": r.name,
                 "auth": r.auth} for r in self.routes]
