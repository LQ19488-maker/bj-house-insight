"""管理与健康检查。

导入接口手写 multipart 解析（`cgi` 已在 Python 3.13 移除），
解析后把文件字节交给 service，由 service 复用 etl 包完成清洗与入库。
"""

from __future__ import annotations

from backend.dto import params
from backend.httpkit import multipart
from backend.httpkit.response import ApiError
from backend.service import admin_service


def health(ctx):
    return admin_service.health()


def import_data(ctx):
    user = ctx.require_login()
    ctype = ctx.headers.get("content-type") or ctx.headers.get("Content-Type") or ""
    fields, files = multipart.parse(ctx.body, ctype)
    item = files.get("file")
    if item is None:
        raise ApiError(1001, "缺少 file 字段（multipart/form-data）")
    dry_run = str(fields.get("dry_run", "false")).strip().lower() in ("1", "true", "yes", "on")
    return admin_service.import_excel(item["filename"], item["data"], dry_run,
                                      int(user["user_id"]))


def batches(ctx):
    page_no, size = params.page(ctx)
    return admin_service.batches(page_no, size)


def batch_report(ctx):
    return admin_service.batch_report(params.path_int(ctx))


def logs(ctx):
    page_no, size = params.page(ctx)
    return admin_service.logs(ctx.qs("action"), page_no, size)
