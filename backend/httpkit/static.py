"""静态资源托管 + SPA 回退（替代 Nginx 的 try_files）。

规则：
  - 非 /api 的 GET：先在 dist 下找真实文件，命中就发；
  - 找不到则发 index.html（状态码 200，不是 404）——这样刷新 /analytics 不会 404；
  - 路径解析后必须仍在 dist 目录内，防 ../ 穿越。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("font/woff2", ".woff2")


def resolve(root: Path, url_path: str) -> tuple[Path | None, str]:
    """返回 (要发送的文件路径, content-type)。找不到返回 (None, '')。"""
    root = root.resolve()
    rel = url_path.lstrip("/")
    candidate = (root / rel).resolve() if rel else None

    if candidate is not None and candidate.is_file():
        # 防目录穿越
        try:
            candidate.relative_to(root)
        except ValueError:
            return None, ""
        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        return candidate, ctype

    index = root / "index.html"
    if index.is_file():
        return index, "text/html; charset=utf-8"
    return None, ""
