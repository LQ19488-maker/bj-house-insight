"""配置：全部从环境变量读取，缺省值保证本机直接可跑。

手册 §10 工程规范要求：敏感信息不入库、不进 Git；因此 JWT_SECRET 只从环境变量来，
缺省时生成一个临时随机值并在启动日志里明确提示"仅适用于本机演示"。
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    db_path: Path
    readonly: bool
    jwt_secret: str
    jwt_secret_ephemeral: bool
    jwt_ttl_seconds: int
    dist_dir: Path
    upload_dir: Path
    max_upload_bytes: int
    version: str

    @property
    def bind_all(self) -> bool:
        return self.host == "0.0.0.0"


def load() -> Config:
    """读取环境变量。见 README「部署前必做 10 条」中的 1/3/4/6 项。"""
    secret = os.environ.get("JWT_SECRET", "").strip()
    ephemeral = False
    if not secret:
        secret = secrets.token_urlsafe(32)
        ephemeral = True

    db_path = Path(os.environ.get("DB_PATH", str(PROJECT_ROOT / "data" / "app.db")))
    dist_dir = Path(os.environ.get("DIST_DIR", str(PROJECT_ROOT / "frontend" / "dist")))
    upload_dir = Path(os.environ.get("UPLOAD_DIR", str(PROJECT_ROOT / "data" / "uploads")))

    return Config(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8080")),
        db_path=db_path,
        readonly=_env_bool("READONLY", False),
        jwt_secret=secret,
        jwt_secret_ephemeral=ephemeral,
        jwt_ttl_seconds=int(os.environ.get("JWT_TTL", "7200")),
        dist_dir=dist_dir,
        upload_dir=upload_dir,
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
        version=os.environ.get("APP_VERSION", "0.1.0"),
    )


_cached: Config | None = None


def get() -> Config:
    """进程内单例。service 层通过它拿 db_path / readonly 等配置。"""
    global _cached
    if _cached is None:
        _cached = load()
    return _cached


def reset() -> None:
    """测试用：丢弃缓存，让下次 get() 重新读环境变量。"""
    global _cached
    _cached = None
