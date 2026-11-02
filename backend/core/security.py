"""安全：密码哈希（PBKDF2-HMAC-SHA256）与 JWT（HS256），全部标准库实现。

手册要求 bcrypt + PyJWT，本机无法安装第三方包，改用等价的标准库方案：
  - 密码：`hashlib.pbkdf2_hmac('sha256', pwd, salt, 200_000)`，格式 `pbkdf2_sha256$迭代数$salt$摘要`
    （NIST SP 800-132 推荐，抗暴力破解强度足够，且无外部依赖）
  - JWT：HS256 本质就是 HMAC-SHA256，header.payload.signature 三段 base64url

已知局限（写入 ADR）：登录失败锁定用进程内字典，多进程部署需换 Redis。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from ..httpkit.response import ApiError

_PBKDF2_ITER = 200_000
_SALT_BYTES = 16


# ---------------------------------------------------------------------------
# base64url
# ---------------------------------------------------------------------------
def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ---------------------------------------------------------------------------
# 密码
# ---------------------------------------------------------------------------
def hash_password(password: str, *, iterations: int = _PBKDF2_ITER) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${b64e(salt)}${b64e(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_s, digest_s = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        salt = b64d(salt_s)
        expected = b64d(digest_s)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def sign_jwt(payload: dict, secret: str, ttl_seconds: int = 7200) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    body = dict(payload)
    body.setdefault("iat", now)
    body["exp"] = now + int(ttl_seconds)

    segs = [b64e(json.dumps(header, separators=(",", ":")).encode()),
            b64e(json.dumps(body, separators=(",", ":")).encode())]
    signing_input = ".".join(segs).encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segs.append(b64e(sig))
    return ".".join(segs)


def verify_jwt(token: str, secret: str) -> dict:
    try:
        header_s, payload_s, sig_s = token.split(".")
    except ValueError:
        raise ApiError(2001, "凭证格式不正确")

    signing_input = f"{header_s}.{payload_s}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual = b64d(sig_s)
    except Exception:
        raise ApiError(2001, "凭证签名无效")
    if not hmac.compare_digest(expected, actual):
        raise ApiError(2001, "凭证签名无效")

    try:
        payload = json.loads(b64d(payload_s))
    except Exception:
        raise ApiError(2001, "凭证载荷无法解析")

    if int(payload.get("exp", 0)) < int(time.time()):
        raise ApiError(2002)
    if "user_id" not in payload:
        raise ApiError(2001, "凭证缺少 user_id")
    return payload
