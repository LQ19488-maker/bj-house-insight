"""压测：验证 NFR 里的性能指标（列表 P95 < 300ms，聚合 P95 < 800ms）。

    python tools/bench.py            # 每个接口打 50 次
    python tools/bench.py --n 100

为什么不用 wrk/ab：本机都没有，且需要按接口分别统计 P50/P95/max 并
对照 NFR 指标做判定，用标准库 threading + urllib 足够，还能顺手输出结论。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API = "http://127.0.0.1:18081"

# (名称, 路径, NFR 目标毫秒)
ENDPOINTS = [
    ("列表查询（默认）", "/api/v1/houses?page=1&page_size=20", 300),
    ("列表查询（多条件）",
     "/api/v1/houses?district_id=11&near_subway=1&price_min=400&price_max=600"
     "&sort=unit_price&order=desc&page=2&page_size=20", 300),
    ("列表查询（朝向多选）", "/api/v1/houses?direction=%E5%8D%97,%E5%8C%97&page_size=50", 300),
    ("房源详情", "/api/v1/houses/1", 300),
    ("相似房源", "/api/v1/houses/1/similar?limit=5", 300),
    ("房源对比", "/api/v1/houses/compare?ids=1,2,3,4", 300),
    ("区级汇总", "/api/v1/analytics/district-summary", 800),
    ("价格分布", "/api/v1/analytics/price-distribution?metric=total&bins=10", 800),
    ("面积总价散点", "/api/v1/analytics/area-price-scatter?limit=500", 800),
    ("房龄趋势", "/api/v1/analytics/age-price-trend", 800),
    ("分区房龄对照", "/api/v1/analytics/age-price-by-district?top_n=6", 800),
    ("溢价（同区控制）", "/api/v1/analytics/premium?metric=metro&control=district", 800),
    ("楼层与朝向", "/api/v1/analytics/floor-orientation?metric=both", 800),
    ("性价比异常", "/api/v1/analytics/value-anomaly?district_id=11&area_band=60-90", 800),
    ("小区画像", "/api/v1/communities/1", 800),
    ("街道排行", "/api/v1/rankings?scope=street&min_count=4&limit=20", 800),
]


def start_server():
    import os
    import shutil

    src = ROOT / "data" / "app.db"
    tmp_db = ROOT / "data" / ".bench.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(tmp_db) + suffix)
        if p.exists():
            p.unlink()
    shutil.copyfile(src, tmp_db)

    os.environ["DB_PATH"] = str(tmp_db)
    os.environ["PORT"] = "18081"
    os.environ["JWT_SECRET"] = "bench-secret"
    os.environ["LOG_ACCESS"] = "0"

    from backend.core import config as config_mod
    config_mod.reset()
    from backend.server import ApiHandler, build_router

    cfg = config_mod.get()
    ApiHandler.router = build_router()

    import threading
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer((cfg.host, cfg.port), ApiHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    return httpd


def hit(path: str) -> float:
    started = time.perf_counter()
    with urllib.request.urlopen(API + path, timeout=30) as resp:
        resp.read()
    return (time.perf_counter() - started) * 1000


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="接口压测")
    ap.add_argument("--n", type=int, default=50, help="每个接口请求次数（默认 50）")
    ap.add_argument("--warmup", type=int, default=3, help="预热次数")
    args = ap.parse_args(argv)

    httpd = start_server()
    rows = []
    try:
        for name, path, target in ENDPOINTS:
            for _ in range(args.warmup):
                hit(path)
            samples = [hit(path) for _ in range(args.n)]
            samples.sort()
            p50 = statistics.median(samples)
            p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
            rows.append({"name": name, "target": target, "p50": p50, "p95": p95,
                         "max": max(samples), "ok": p95 <= target})
    finally:
        httpd.shutdown()

    print("=" * 92)
    print(f"接口压测（每接口 {args.n} 次，含 {args.warmup} 次预热）")
    print("=" * 92)
    print(f"{'接口':<22}{'目标 P95':>10}{'P50':>10}{'P95':>10}{'max':>10}   结论")
    print("-" * 92)
    failed = 0
    for r in rows:
        if not r["ok"]:
            failed += 1
        print(f"{r['name']:<22}{r['target']:>8}ms{r['p50']:>9.1f}ms{r['p95']:>9.1f}ms"
              f"{r['max']:>9.1f}ms   {'OK' if r['ok'] else 'FAIL 超目标'}")
    print("-" * 92)
    worst = max(rows, key=lambda r: r["p95"])
    print(f"最慢接口：{worst['name']} P95 = {worst['p95']:.1f}ms")
    print(f"压测结论：{len(rows) - failed}/{len(rows)} 达到 NFR 目标")
    print("=" * 92)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
