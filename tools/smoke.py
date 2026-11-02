"""全接口冒烟测试：在进程内启动服务，逐个真实调用 29 个接口。

    python tools/smoke.py

为什么不用 curl：需要断言响应码、业务 code、关键字段与守恒关系
（如"直方图各桶之和 == 总数"），curl 只能看到原始 JSON。
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API = "http://127.0.0.1:18080"   # 冒烟专用端口，避免和开发服务器冲突


# ---------------------------------------------------------------------------
def start_server():
    import os
    import shutil

    # 冒烟会写收藏/日志/估价记录，必须在**数据库副本**上跑，不能污染交付用的 data/app.db
    tmp_db = ROOT / "data" / ".smoke.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(tmp_db) + suffix)
        if p.exists():
            p.unlink()
    shutil.copyfile(ROOT / "data" / "app.db", tmp_db)

    os.environ["DB_PATH"] = str(tmp_db)
    os.environ["PORT"] = "18080"
    os.environ["JWT_SECRET"] = "smoke-test-secret"
    os.environ["LOG_ACCESS"] = "0"   # 冒烟时关掉访问日志，避免刷屏

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
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.4)
    return httpd


def call(method: str, path: str, *, token: str | None = None,
         body: dict | None = None, raw: bytes | None = None,
         content_type: str = "application/json") -> tuple[int, dict]:
    url = API + quote(path, safe="/?=&%")
    data = raw if raw is not None else (
        json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(payload)
        except json.JSONDecodeError:
            return exc.code, {"raw": payload}


# ---------------------------------------------------------------------------
checks: list[dict] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def code_is(name: str, status: int, body: dict, expect_status: int, expect_code: int) -> bool:
    ok = status == expect_status and body.get("code") == expect_code
    check(name, ok, f"HTTP {status} / code {body.get('code')}"
          + ("" if ok else f"  期望 HTTP {expect_status} / code {expect_code}"
             f"  返回 {str(body)[:160]}"))
    return ok


def main() -> int:
    httpd = start_server()
    try:
        # ---------- 健康检查 ----------
        st, b = call("GET", "/api/v1/health")
        code_is("GET /health", st, b, 200, 0)
        check("health.house_rows = 2890", b.get("data", {}).get("house_rows") == 2890,
              str(b.get("data")))
        check("health.db = up", b.get("data", {}).get("db") == "up")

        # ---------- 元数据 ----------
        st, b = call("GET", "/api/v1/meta/districts")
        code_is("GET /meta/districts", st, b, 200, 0)
        check("区字典 17 条", len(b["data"]["list"]) == 17, str(len(b["data"]["list"])))

        st, b = call("GET", "/api/v1/meta/streets?district_id=1")
        code_is("GET /meta/streets?district_id=1", st, b, 200, 0)
        check("街道按区联动（东城 > 0）", len(b["data"]["list"]) > 0)

        st, b = call("GET", "/api/v1/meta/streets?include_pseudo=true")
        pseudo = [s for s in b["data"]["list"] if s["is_pseudo"] == 1]
        check("include_pseudo=true 能看见伪街道", len(pseudo) > 0, f"{len(pseudo)} 条")

        st, b = call("GET", "/api/v1/meta/streets")
        check("默认排除伪街道", all(s["is_pseudo"] == 0 for s in b["data"]["list"]))

        st, b = call("GET", "/api/v1/meta/filters")
        code_is("GET /meta/filters", st, b, 200, 0)
        check("filters 含 5 组枚举与 ranges",
              {"decoration", "structure", "direction", "floor_level", "ranges"}
              <= set(b["data"].keys()))

        # ---------- 检索 ----------
        st, b = call("GET", "/api/v1/houses")
        code_is("GET /houses 默认", st, b, 200, 0)
        check("默认 total = 2890", b["data"]["total"] == 2890, str(b["data"]["total"]))
        check("默认 page_size = 20", len(b["data"]["list"]) == 20)
        check("HouseCard 含 21 个契约字段",
              len(b["data"]["list"][0]) == 21, str(len(b["data"]["list"][0])))

        st, b2 = call("GET", "/api/v1/houses?district_id=11&near_subway=1")
        check("组合筛选命中数 < 2890", 0 < b2["data"]["total"] < 2890, str(b2["data"]["total"]))

        st, b3 = call("GET", "/api/v1/houses?district_id=11&near_subway=1&page=2&page_size=5")
        check("分页 total 与筛选一致（total 复用同一 where 构造器）",
              b3["data"]["total"] == b2["data"]["total"],
              f'{b3["data"]["total"]} vs {b2["data"]["total"]}')

        st, b4 = call("GET", "/api/v1/houses?direction=南,北")
        check("朝向多选筛选生效", b4["data"]["total"] > 0, str(b4["data"]["total"]))
        check("朝向筛选不等于全量", b4["data"]["total"] != 2890)

        st, b5 = call("GET", "/api/v1/houses?sort=unit_price&order=desc")
        prices = [x["unit_price"] for x in b5["data"]["list"]]
        check("按单价降序生效", prices == sorted(prices, reverse=True))

        st, b = call("GET", "/api/v1/houses?sort=drop%20table")
        code_is("非法排序 → 1002", st, b, 400, 1002)

        st, b = call("GET", "/api/v1/houses?page_size=1000")
        code_is("page_size=1000 → 1003", st, b, 400, 1003)

        st, b = call("GET", "/api/v1/houses?price_min=600&price_max=400")
        code_is("price_min>max → 1001", st, b, 400, 1001)

        st, b = call("GET", "/api/v1/houses?keyword=%E9%93%B6%E6%B2%B3")   # 银河
        code_is("关键词检索", st, b, 200, 0)

        st, b = call("GET", "/api/v1/houses?room=2&hall=0")
        check("厅=0 可查（合法值）", st == 200 and b["code"] == 0 and b["data"]["total"] >= 0,
              str(b["data"]["total"]))

        # ---------- 详情 / 相似 / 对比 ----------
        st, b = call("GET", "/api/v1/houses/1")
        code_is("GET /houses/1", st, b, 200, 0)
        d = b["data"]
        check("详情含 directions（M:N 展开）", isinstance(d.get("directions"), list)
              and len(d["directions"]) >= 1, str(d.get("directions")))
        check("详情含同区分位", isinstance(d.get("district_percentile"), (int, float)),
              str(d.get("district_percentile")))
        check("详情含 community 快照", isinstance(d.get("community"), dict))
        check("详情含相似房源", isinstance(d.get("similar"), list))

        st, b = call("GET", "/api/v1/houses/999999")
        code_is("不存在的房源 → 3001", st, b, 404, 3001)

        st, b = call("GET", "/api/v1/houses/abc")
        code_is("非整数 id → 1001", st, b, 400, 1001)

        st, b = call("GET", "/api/v1/houses/1/similar?limit=3")
        code_is("GET /houses/1/similar", st, b, 200, 0)
        check("相似房源返回 fallback_level",
              b["data"].get("fallback_level") in ("community", "street", "district", "none"),
              str(b["data"].get("fallback_level")))

        st, b = call("GET", "/api/v1/houses/compare?ids=1,2,3")
        code_is("GET /houses/compare", st, b, 200, 0)
        check("对比 12 个属性", len(b["data"]["attributes"]) == 12,
              str(len(b["data"]["attributes"])))
        check("雷达含 normalize_range（否则形状不可比）",
              "normalize_range" in b["data"]["radar"])
        check("雷达 5 维", len(b["data"]["radar"]["dimensions"]) == 5)

        st, b = call("GET", "/api/v1/houses/compare?ids=1,2,3,4,5")
        code_is("对比 5 条 → 1001", st, b, 400, 1001)

        # ---------- 分析看板 ----------
        st, b = call("GET", "/api/v1/analytics/district-summary")
        code_is("GET /analytics/district-summary", st, b, 200, 0)
        check("区汇总 17 条", len(b["data"]["list"]) == 17)
        xicheng = next(x for x in b["data"]["list"] if x["district_name"] == "西城")
        check("西城均价 129520.46", abs(xicheng["avg_unit_price"] - 129520.46) < 0.01,
              str(xicheng["avg_unit_price"]))

        st, b = call("GET", "/api/v1/analytics/price-distribution?metric=total&bins=10")
        code_is("GET /analytics/price-distribution", st, b, 200, 0)
        bins_total = sum(x["count"] for x in b["data"]["bins"])
        check("直方图各桶之和 == 总数（数值断言）",
              bins_total == b["data"]["total"] == 2890,
              f'{bins_total} / {b["data"]["total"]}')
        check("默认分位分桶", b["data"]["binning"] == "quantile")

        st, b = call("GET", "/api/v1/analytics/area-price-scatter?limit=200")
        code_is("GET /analytics/area-price-scatter", st, b, 200, 0)
        check("皮尔逊 r ≈ 0.719", abs(b["data"]["pearson_r"] - 0.719) < 0.01,
              str(b["data"]["pearson_r"]))
        check("散点 n = 全量 2890（r 由全量算）", b["data"]["n"] == 2890)
        check("抽样点 ≤ limit", len(b["data"]["points"]) <= 200)

        st, b = call("GET", "/api/v1/analytics/age-price-trend")
        code_is("GET /analytics/age-price-trend", st, b, 200, 0)
        check("房龄 8 段", len(b["data"]["buckets"]) == 8, str(len(b["data"]["buckets"])))
        check("房龄-单价 r ≈ 0.260", abs(b["data"]["pearson_r"] - 0.260) < 0.01,
              str(b["data"]["pearson_r"]))

        st, b = call("GET", "/api/v1/analytics/age-price-by-district?top_n=6")
        code_is("GET /analytics/age-price-by-district", st, b, 200, 0)
        check("分区房龄 6 条线", len(b["data"]["series"]) == 6)
        check("每个点 n ≥ 3（n<3 不输出）",
              all(p["n"] >= 3 for s in b["data"]["series"] for p in s["points"]))

        st, b = call("GET", "/api/v1/analytics/premium?metric=metro&control=district")
        code_is("GET /analytics/premium?metric=metro", st, b, 200, 0)
        metro = next(g for g in b["data"]["groups"] if g["group"] == "近地铁")
        check("地铁溢价 +27.44%", abs(metro["premium_pct"] - 27.44) < 0.05,
              str(metro["premium_pct"]))
        check("溢价含同区控制 by_district", len(b["data"].get("by_district", [])) > 0)
        check("溢价回传 caliber（口径说明）", bool(b["data"].get("caliber")))

        st, b = call("GET", "/api/v1/analytics/premium?metric=structure&control=none")
        check("结构溢价里平房/独栋标记样本不足",
              any(g["insufficient_sample"] for g in b["data"]["groups"]),
              str([(g["group"], g["n"]) for g in b["data"]["groups"]]))

        st, b = call("GET", "/api/v1/analytics/premium?metric=bad")
        code_is("非法 metric → 1001", st, b, 400, 1001)

        st, b = call("GET", "/api/v1/analytics/floor-orientation?metric=both")
        code_is("GET /analytics/floor-orientation", st, b, 200, 0)
        check("楼层含“未知”单列", any(x["level"] == "未知" for x in b["data"]["floor"]))
        check("朝南 > 朝北（溢价 ~1.8%）",
              b["data"]["orientation_spread"]["south_minus_north_pct"] > 0,
              str(b["data"]["orientation_spread"]))

        st, b = call("GET", "/api/v1/analytics/value-anomaly?district_id=11&area_band=60-90")
        code_is("GET /analytics/value-anomaly", st, b, 200, 0)
        check("异常房源按同区同面积段判定", b["data"]["group"]["n"] > 0,
              str(b["data"]["group"]))

        # ---------- 小区与排行 ----------
        st, b = call("GET", "/api/v1/communities/1")
        code_is("GET /communities/1", st, b, 200, 0)
        check("小区画像含 street_rank", isinstance(b["data"].get("street_rank"), list))

        st, b = call("GET", "/api/v1/rankings?scope=street&min_count=4&limit=10")
        code_is("GET /rankings?scope=street", st, b, 200, 0)
        check("街道排行排除伪街道",
              all(r["is_pseudo"] == 0 for r in b["data"]["list"]),
              str([r["name"] for r in b["data"]["list"] if r["is_pseudo"] == 1]))
        check("min_count 生效", all(r["house_count"] >= 4 for r in b["data"]["list"]))
        check("excluded_pseudo = 16", b["data"]["excluded_pseudo"] == 16,
              str(b["data"]["excluded_pseudo"]))

        st, b = call("GET", "/api/v1/rankings?scope=bad")
        code_is("非法 scope → 1001", st, b, 400, 1001)

        # ---------- 估价 ----------
        payload = {"district_id": 11, "street_id": None, "area": 80, "room": 2, "hall": 1,
                   "age": 10, "decoration": "精装", "floor_level": "中", "near_subway": 1}
        st, b = call("POST", "/api/v1/valuation", body=payload)
        code_is("POST /valuation", st, b, 200, 0)
        v = b["data"]
        check("估价返回区间与置信度",
              v["price_range"] is not None and v["confidence"] in ("high", "medium", "low"),
              str({k: v.get(k) for k in ("sample_count", "confidence", "fallback_level")}))
        check("估价回传样本数与降级层级",
              isinstance(v["sample_count"], int) and v["fallback_level"] in
              ("community", "street", "district", "none"))
        check("估价带免责文案", "仅供参考" in (v.get("disclaimer") or ""))

        bad = dict(payload, area=5)
        st, b = call("POST", "/api/v1/valuation", body=bad)
        code_is("面积 5 → 1001", st, b, 400, 1001)

        bad2 = dict(payload, district_id=999)
        st, b = call("POST", "/api/v1/valuation", body=bad2)
        code_is("不存在的区 → 3001", st, b, 404, 3001)

        # ---------- 认证 ----------
        st, b = call("POST", "/api/v1/auth/login",
                     body={"username": "admin", "password": "admin1234"})
        code_is("POST /auth/login（admin）", st, b, 200, 0)
        admin_token = b["data"]["token"]
        check("登录返回 role", b["data"]["user"]["role"] == "admin")

        st, b = call("POST", "/api/v1/auth/login",
                     body={"username": "admin", "password": "wrong-pass"})
        code_is("密码错误 → 2001", st, b, 401, 2001)

        st, b = call("POST", "/api/v1/auth/login",
                     body={"username": "user", "password": "user1234"})
        user_token = b["data"]["token"] if b.get("code") == 0 else None
        code_is("POST /auth/login（user）", st, b, 200, 0)

        st, b = call("GET", "/api/v1/auth/me", token=admin_token)
        code_is("GET /auth/me", st, b, 200, 0)
        check("me.username = admin", b["data"]["username"] == "admin")

        st, b = call("GET", "/api/v1/auth/me")
        code_is("无 token → 2001", st, b, 401, 2001)

        st, b = call("GET", "/api/v1/auth/me", token="bad.token.value")
        code_is("非法 token → 2001", st, b, 401, 2001)

        # ---------- 收藏 ----------
        st, b = call("POST", "/api/v1/favorites/1", token=user_token)
        code_is("POST /favorites/1", st, b, 200, 0)
        st, b = call("POST", "/api/v1/favorites/1", token=user_token)
        check("重复收藏幂等（already=true）",
              b["code"] == 0 and b["data"]["already"] is True, str(b.get("data")))

        st, b = call("GET", "/api/v1/favorites", token=user_token)
        code_is("GET /favorites", st, b, 200, 0)
        check("收藏列表包含刚收藏的房源",
              any(x["house_id"] == 1 for x in b["data"]["list"]))

        st, b = call("DELETE", "/api/v1/favorites/1", token=user_token)
        code_is("DELETE /favorites/1", st, b, 200, 0)

        st, b = call("POST", "/api/v1/favorites/1")
        code_is("未登录收藏 → 2001", st, b, 401, 2001)

        # ---------- 管理 ----------
        st, b = call("GET", "/api/v1/admin/batches", token=user_token)
        code_is("user 访问 admin → 2003", st, b, 403, 2003)

        st, b = call("GET", "/api/v1/admin/batches", token=admin_token)
        code_is("GET /admin/batches（admin）", st, b, 200, 0)
        check("批次列表至少有 seed 批次", b["data"]["total"] >= 1)

        seed_batch = b["data"]["list"][-1]["batch_id"]
        st, b = call("GET", f"/api/v1/admin/batches/{seed_batch}/report", token=admin_token)
        code_is("GET /admin/batches/{id}/report", st, b, 200, 0)
        check("质量报告行数漏斗自洽", b["data"]["funnel"]["self_consistent"] is True)
        check("质量报告含规则触发统计", len(b["data"]["rules_triggered"]) > 0,
              str(b["data"]["rules_triggered"]))

        st, b = call("GET", "/api/v1/admin/logs", token=admin_token)
        code_is("GET /admin/logs", st, b, 200, 0)

        # 导入 dry-run（真实上传 xlsx，走 multipart + 复用 ETL）
        xlsx = ROOT / "data" / "raw" / "最新发布的北京二手房数据_预处理.xlsx"
        if xlsx.exists():
            boundary = "----smoke boundary 12345"
            head = (f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="file"; filename="data.xlsx"\r\n'
                    "Content-Type: application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet\r\n\r\n").encode()
            tail = (f"\r\n--{boundary}\r\n"
                    'Content-Disposition: form-data; name="dry_run"\r\n\r\ntrue'
                    f"\r\n--{boundary}--\r\n").encode()
            st, b = call("POST", "/api/v1/admin/import", token=admin_token,
                         raw=head + xlsx.read_bytes() + tail,
                         content_type=f"multipart/form-data; boundary={boundary}")
            code_is("POST /admin/import?dry_run=true", st, b, 200, 0)
            rep = b.get("data", {})
            check("导入 dry-run 复用 ETL：2890 行全部保留",
                  rep.get("loaded_rows") == 2890 and rep.get("rejected_rows") == 0,
                  str({k: rep.get(k) for k in ("total_rows", "loaded_rows", "rejected_rows")}))
            check("dry-run 不写库（batch_id 为空）", rep.get("batch_id") is None)
            check("dry-run 报告含规则触发统计", len(rep.get("rules_triggered", {})) > 0,
                  str(rep.get("rules_triggered")))
            check("dry-run 质量断言全通过",
                  not rep.get("assertions", {}).get("failed"),
                  str(rep.get("assertions", {}).get("failed")))

        # ---------- 错误路径 ----------
        st, b = call("GET", "/api/v1/nope")
        code_is("不存在的接口 → 3001", st, b, 404, 3001)

        st, b = call("GET", "/some-frontend-route")
        code_is("静态未构建 → 404 且给提示", st, b, 404, 3001)
        check("静态提示包含构建说明", "npm run build" in (b.get("message") or ""),
              b.get("message", "")[:80])

    finally:
        httpd.shutdown()

    # ---------- 输出 ----------
    print("=" * 78)
    print("全接口冒烟测试（进程内启动，逐接口真实调用）")
    print("=" * 78)
    failed = 0
    for i, c in enumerate(checks, 1):
        mark = "OK  " if c["passed"] else "FAIL"
        if not c["passed"]:
            failed += 1
        print(f"[{mark}] {i:>2}. {c['name']}"
              + (f"  — {c['detail']}" if c["detail"] and not c["passed"] else ""))
    print("-" * 78)
    print(f"冒烟结果：{len(checks) - failed}/{len(checks)} 通过")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
