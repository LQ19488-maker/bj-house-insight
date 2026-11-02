"""双模式一致性检查：静态模式 vs 接口模式，同一批请求必须算出同样的数字。

    python tools/check_parity.py

为什么必须检查：页面组件共用一套，但数据层有 httpSource 与 staticSource 两份实现。
两份实现一旦口径分叉，Pages 上看到的数字就和本机不同 —— 而这种差异在浏览器里
极难发现。本脚本启动后端，让 Node 同时调用两套实现并逐字段比对。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = 18082


def start_backend():
    import os

    tmp_db = ROOT / "data" / ".parity.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(tmp_db) + suffix)
        if p.exists():
            p.unlink()
    shutil.copyfile(ROOT / "data" / "app.db", tmp_db)

    os.environ["DB_PATH"] = str(tmp_db)
    os.environ["PORT"] = str(PORT)
    os.environ["JWT_SECRET"] = "parity-secret"
    os.environ["LOG_ACCESS"] = "0"

    from backend.core import config as config_mod
    config_mod.reset()
    from backend.core import db as db_mod
    from backend.server import ApiHandler, build_router

    cfg = config_mod.get()
    db_mod.ensure_demo_users(cfg.db_path)
    ApiHandler.router = build_router()

    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer((cfg.host, cfg.port), ApiHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.5)
    return httpd, tmp_db


def main() -> int:
    houses = ROOT / "frontend" / "public" / "data" / "houses.json"
    if not houses.exists():
        print("缺少 frontend/public/data/houses.json，请先运行：python tools/export_static.py",
              file=sys.stderr)
        return 2

    httpd, tmp_db = start_backend()
    try:
        proc = subprocess.run(
            ["node", str(ROOT / "tools" / "parity.mjs"), str(ROOT), f"http://127.0.0.1:{PORT}"],
            capture_output=True, text=True, encoding="utf-8", timeout=180
        )
    finally:
        httpd.shutdown()
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(tmp_db) + suffix)
            if p.exists():
                p.unlink()

    if not proc.stdout.strip():
        print("Node 输出为空，stderr：", file=sys.stderr)
        print(proc.stderr[:2000], file=sys.stderr)
        return 2

    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print("无法解析 Node 输出：", file=sys.stderr)
        print(proc.stdout[:2000], file=sys.stderr)
        print(proc.stderr[:2000], file=sys.stderr)
        return 2

    print("=" * 78)
    print("双模式一致性检查（staticSource vs httpSource，逐字段比对）")
    print("=" * 78)
    failed = 0
    for r in report["results"]:
        mark = "OK  " if r["ok"] else "FAIL"
        if not r["ok"]:
            failed += 1
        print(f"[{mark}] {r['name']}")
        if not r["ok"]:
            for d in r["diffs"]:
                print(f"        {d}")
    print("-" * 78)
    print(f"一致性：{report['total'] - failed}/{report['total']} 通过")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
