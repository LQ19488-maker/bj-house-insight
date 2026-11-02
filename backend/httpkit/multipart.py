"""手写 multipart/form-data 解析。

为什么必须自己写：`cgi` 模块在 Python 3.13 已被移除（PEP 594），
而导入接口需要接收 .xlsx 文件上传。

只实现 RFC 7578 中用得到的子集：
  - 单个 boundary
  - 每个 part 的 content-disposition 的 name / filename
  - 不做嵌套 multipart、不做 base64 transfer-encoding（浏览器不会发）
"""

from __future__ import annotations

import re
from email.parser import HeaderParser

from .response import ApiError


def parse_boundary(content_type: str) -> bytes:
    if "multipart/form-data" not in content_type.lower():
        raise ApiError(1001, "请求必须是 multipart/form-data")
    m = re.search(r'boundary=("?)([^";]+)\1', content_type, re.I)
    if not m:
        raise ApiError(1001, "multipart 缺少 boundary")
    return m.group(2).strip().encode("utf-8")


def parse(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, dict]]:
    """返回 (普通字段, 文件字段)。

    文件字段结构：{"filename": str, "content_type": str, "data": bytes}
    """
    boundary = parse_boundary(content_type)
    delim = b"--" + boundary
    parser = HeaderParser()

    fields: dict[str, str] = {}
    files: dict[str, dict] = {}

    # 以分隔符切分；第一段是 preamble，最后一段是 end delimiter
    parts = body.split(delim)
    for raw in parts:
        # 去掉开头的 \r\n
        if raw.startswith(b"\r\n"):
            raw = raw[2:]
        if not raw or raw.strip() in (b"", b"--"):
            continue
        if raw.endswith(b"--"):
            raw = raw[:-2]
        if raw.startswith(b"--"):
            continue
        if b"\r\n\r\n" not in raw:
            continue
        head, data = raw.split(b"\r\n\r\n", 1)
        # 结尾会带一个 CRLF（属于分隔符的一部分）
        if data.endswith(b"\r\n"):
            data = data[:-2]

        headers = parser.parsestr(head.decode("utf-8", "replace"))
        disposition = headers.get("Content-Disposition", "")
        name_m = re.search(r'name="([^"]*)"', disposition)
        if not name_m:
            continue
        name = name_m.group(1)
        file_m = re.search(r'filename="([^"]*)"', disposition)
        if file_m is not None:
            files[name] = {
                "filename": file_m.group(1),
                "content_type": headers.get("Content-Type", "application/octet-stream"),
                "data": data,
            }
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files
