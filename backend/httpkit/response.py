"""统一响应体与业务错误码。

手册要求：统一 {code, message, data, request_id}；错误码 ≥ 10 个。
本模块只有这一件事——不放任何业务逻辑。
"""

from __future__ import annotations

import json
from typing import Any

# 错误码 → (HTTP 状态, 默认中文文案)
CODES: dict[int, tuple[int, str]] = {
    0: (200, "ok"),
    1001: (400, "参数校验失败"),
    1002: (400, "非法排序字段"),
    1003: (400, "分页超限"),
    2001: (401, "未登录或凭证缺失"),
    2002: (401, "凭证已过期"),
    2003: (403, "权限不足"),
    2004: (423, "账号已锁定"),
    3001: (404, "资源不存在"),
    4001: (400, "文件类型不支持"),
    4002: (400, "文件过大"),
    5000: (500, "服务器内部错误"),
}


class ApiError(Exception):
    """业务异常。handler/service 抛出，由 server 统一转成响应体。"""

    def __init__(self, code: int, message: str | None = None, *, detail: Any = None):
        self.code = int(code)
        status, default_msg = CODES.get(self.code, (500, "未知错误"))
        self.http_status = status
        self.message = message or default_msg
        self.detail = detail
        super().__init__(self.message)

    def __repr__(self) -> str:  # pragma: no cover
        return f"ApiError({self.code}, {self.message!r})"


def ok(data: Any, request_id: str = "") -> dict:
    return {"code": 0, "message": "ok", "data": data, "request_id": request_id}


def fail(err: ApiError, request_id: str = "", *, detail: Any = None) -> dict:
    body = {"code": err.code, "message": err.message, "data": None, "request_id": request_id}
    if detail is not None:
        body["detail"] = detail
    elif err.detail is not None:
        body["detail"] = err.detail
    return body


def dumps(obj: Any) -> bytes:
    """统一 JSON 序列化：中文不转义、紧凑、UTF-8。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
