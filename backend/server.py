"""服务入口：装配路由表 + 中间件 + 静态托管，启动 ThreadingHTTPServer。

启动：
    python backend/server.py                # 默认 127.0.0.1:8080
    PORT=8000 python backend/server.py      # PaaS 会注入 PORT
    HOST=0.0.0.0 python backend/server.py   # 容器内必须绑 0.0.0.0

为什么每请求 `Connection: close`：自写服务器最容易挂在 keep-alive 的半关闭连接上。
本项目单请求耗时 <50ms，关闭连接的开销可以忽略，换来的是稳定。
"""

from __future__ import annotations

import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api.handler import (  # noqa: E402
    admin as h_admin,
    analytics as h_analytics,
    auth as h_auth,
    community as h_community,
    favorite as h_favorite,
    house as h_house,
    meta as h_meta,
    valuation as h_valuation,
)
from backend.core import config as config_mod  # noqa: E402
from backend.core import db as db_mod  # noqa: E402
from backend.core.security import verify_jwt  # noqa: E402
from backend.httpkit import middleware, static  # noqa: E402
from backend.httpkit.ctx import Ctx  # noqa: E402
from backend.httpkit.response import ApiError, dumps, fail, ok  # noqa: E402
from backend.httpkit.router import ADMIN, LOGIN, OPTIONAL, PUBLIC, Router  # noqa: E402

API = "/api/v1"
MAX_BODY_BYTES = 25 * 1024 * 1024  # 略高于 20MB 的导入上限，留给 multipart 头部


def build_router() -> Router:
    r = Router()
    # --- 健康检查 ---
    r.add("GET", f"{API}/health", h_admin.health, name="health", auth=PUBLIC)

    # --- 元数据 ---
    r.add("GET", f"{API}/meta/districts", h_meta.districts, name="meta.districts")
    r.add("GET", f"{API}/meta/streets", h_meta.streets, name="meta.streets")
    r.add("GET", f"{API}/meta/filters", h_meta.filters, name="meta.filters")

    # --- 检索 / 详情 / 对比 ---
    r.add("GET", f"{API}/houses", h_house.list_houses, name="houses.list")
    r.add("GET", f"{API}/houses/compare", h_house.compare, name="houses.compare")
    r.add("GET", f"{API}/houses/{{id}}", h_house.detail, name="houses.detail")
    r.add("GET", f"{API}/houses/{{id}}/similar", h_house.similar, name="houses.similar")

    # --- 分析看板 ---
    r.add("GET", f"{API}/analytics/district-summary", h_analytics.district_summary,
          name="analytics.district_summary")
    r.add("GET", f"{API}/analytics/price-distribution", h_analytics.price_distribution,
          name="analytics.price_distribution")
    r.add("GET", f"{API}/analytics/area-price-scatter", h_analytics.area_price_scatter,
          name="analytics.area_price_scatter")
    r.add("GET", f"{API}/analytics/age-price-trend", h_analytics.age_price_trend,
          name="analytics.age_price_trend")
    r.add("GET", f"{API}/analytics/age-price-by-district", h_analytics.age_price_by_district,
          name="analytics.age_price_by_district")
    r.add("GET", f"{API}/analytics/premium", h_analytics.premium, name="analytics.premium")
    r.add("GET", f"{API}/analytics/floor-orientation", h_analytics.floor_orientation,
          name="analytics.floor_orientation")
    r.add("GET", f"{API}/analytics/layout-distribution", h_analytics.layout_distribution,
          name="analytics.layout_distribution")
    r.add("GET", f"{API}/analytics/value-anomaly", h_house.anomaly,
          name="analytics.value_anomaly")

    # --- 小区与排行 ---
    r.add("GET", f"{API}/communities/{{id}}", h_community.community, name="communities.detail")
    r.add("GET", f"{API}/rankings", h_community.rankings, name="rankings")

    # --- 估价 ---
    r.add("POST", f"{API}/valuation", h_valuation.estimate, name="valuation",
          auth=OPTIONAL)

    # --- 认证 ---
    r.add("POST", f"{API}/auth/register", h_auth.register, name="auth.register")
    r.add("POST", f"{API}/auth/login", h_auth.login, name="auth.login")
    r.add("GET", f"{API}/auth/me", h_auth.me, name="auth.me", auth=LOGIN)

    # --- 收藏 ---
    r.add("POST", f"{API}/favorites/{{house_id}}", h_favorite.add, name="favorites.add",
          auth=LOGIN)
    r.add("DELETE", f"{API}/favorites/{{house_id}}", h_favorite.remove,
          name="favorites.remove", auth=LOGIN)
    r.add("GET", f"{API}/favorites", h_favorite.list_favorites, name="favorites.list",
          auth=LOGIN)

    # --- 管理 ---
    r.add("POST", f"{API}/admin/import", h_admin.import_data, name="admin.import",
          auth=ADMIN)
    r.add("GET", f"{API}/admin/batches", h_admin.batches, name="admin.batches", auth=ADMIN)
    r.add("GET", f"{API}/admin/batches/{{id}}/report", h_admin.batch_report,
          name="admin.batch_report", auth=ADMIN)
    r.add("GET", f"{API}/admin/logs", h_admin.logs, name="admin.logs", auth=ADMIN)

    return r


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "BJHouseInsight/0.1"
    protocol_version = "HTTP/1.1"
    router: Router = None  # 由 main 注入

    # ---------------- 框架钩子 ----------------
    def log_message(self, fmt, *args):  # 关掉默认 stderr 日志，用我们自己的 JSON 日志
        return

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in middleware.cors_headers(self.headers.get("Origin")).items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")

    # ---------------- 核心分发 ----------------
    def _handle(self, method: str) -> None:
        cfg = config_mod.get()
        started = time.perf_counter()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        ctx = Ctx(
            method=method,
            path=path,
            query=parse_qs(parsed.query, keep_blank_values=True),
            headers={k.lower(): v for k, v in self.headers.items()},
            request_id=middleware.new_request_id(),
        )

        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                raise ApiError(4002, "请求体过大")
            ctx.body = self.rfile.read(length) if length else b""

            if not path.startswith(API):
                self._serve_static(cfg, path, ctx, started)
                return

            route, params = self.router.match(method, path)
            if route is None:
                if params.get("__path_matched__"):
                    raise ApiError(1001, f"路径已定义但不支持 {method} 方法")
                raise ApiError(3001, f"接口不存在：{path}")

            ctx.params = params
            ctx.route_name = route.name
            middleware.check_auth(route, ctx,
                                 lambda token: verify_jwt(token, cfg.jwt_secret))
            data = route.handler(ctx)
            self._send_json(200, ok(data, ctx.request_id), ctx)
            middleware.log_access(ctx, 200, 0, started)

        except ApiError as err:
            self._send_json(err.http_status, fail(err, ctx.request_id), ctx)
            middleware.log_access(ctx, err.http_status, err.code, started)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # 未知异常：不把堆栈吐给客户端
            sys.stderr.write(f"[{ctx.request_id}] unhandled: {exc}\n")
            traceback.print_exc()
            err = ApiError(5000)
            self._send_json(500, fail(err, ctx.request_id), ctx)
            middleware.log_access(ctx, 500, err.code, started)

    # ---------------- 输出 ----------------
    def _send_json(self, status: int, body: dict, ctx: Ctx) -> None:
        self._send(status, dumps(body), "application/json; charset=utf-8",
                   {"X-Request-Id": ctx.request_id})

    def _serve_static(self, cfg, path: str, ctx: Ctx, started: float) -> None:
        target, ctype = static.resolve(cfg.dist_dir, path)
        if target is None:
            hint = (f"前端未构建：{cfg.dist_dir} 下没有 index.html。"
                    "请先执行 npm run build，或用 /api/v1/health 验证后端。")
            self._send_json(404, fail(ApiError(3001, hint), ctx.request_id), ctx)
            middleware.log_access(ctx, 404, 3001, started)
            return
        self._send(200, target.read_bytes(), ctype, {"X-Request-Id": ctx.request_id})
        middleware.log_access(ctx, 200, 0, started)

    def _send(self, status: int, body: bytes, content_type: str,
              extra: dict | None = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in middleware.cors_headers(self.headers.get("Origin")).items():
                self.send_header(k, v)
            self.send_header("Connection", "close")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main() -> int:
    cfg = config_mod.get()

    if not Path(cfg.db_path).exists():
        print(f"[错误] 数据库不存在：{cfg.db_path}")
        print("       请先运行：run-etl.cmd --db")
        return 2

    created = db_mod.ensure_demo_users(cfg.db_path)

    ApiHandler.router = build_router()
    httpd = ThreadingHTTPServer((cfg.host, cfg.port), ApiHandler)
    httpd.daemon_threads = True

    print("=" * 72)
    print(" 北京二手房行情洞察系统 · 后端")
    print("=" * 72)
    print(f" 监听       http://{cfg.host}:{cfg.port}")
    print(f" 数据库     {cfg.db_path}")
    print(f" 静态目录   {cfg.dist_dir} {'(已构建)' if cfg.dist_dir.is_dir() else '(未构建)'}")
    print(f" 只读模式   {cfg.readonly}")
    print(f" 接口数     {len(ApiHandler.router.routes)}")
    print(f" 健康检查   http://{cfg.host}:{cfg.port}{API}/health")
    if created:
        print(f" 演示账号   已创建 {created}（admin/admin1234, user/user1234）")
    if cfg.jwt_secret_ephemeral:
        print(" [提示] 未设置 JWT_SECRET，已生成临时密钥：重启后旧 token 失效（仅本机演示可用）")
    print("=" * 72)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n收到中断，正在关闭…")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
