"""前端死链检查：源码里所有跳转目标必须命中路由表。

    python tools/check_links.py

为什么需要：页面上的"能点但没内容"比"少一个入口"更伤体验。
本脚本从 src/router/index.js 解析路由表，再扫描所有 .vue 源码里的
`to="..."` / `router.push('...')` / `go(...)` 目标，逐个比对。
动态路径（含 ${...}）会把占位符替换成 X 后再匹配 `:param` 路由。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"

checks: list[dict] = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def parse_routes() -> list[str]:
    text = (FRONTEND / "router" / "index.js").read_text(encoding="utf-8")
    routes = re.findall(r"path:\s*'([^']+)'", text) + re.findall(r"path:\s*\"([^\"]+)\"", text)
    return [r for r in routes if r.startswith("/")]


def route_regex(pattern: str) -> re.Pattern:
    expr = re.sub(r":\w+(\([^)]*\))?", "X", pattern)
    return re.compile("^" + re.escape(expr).replace("X", "[^/]+") + "$")


def collect_targets() -> dict[str, set[str]]:
    """返回 {文件: {目标路径}}

    覆盖的写法（本项目实际用到的全部形态）：
      to="/search"                    静态属性
      :to="'/search'"                 绑定静态字符串
      :to="`/houses/${row.id}`"        绑定模板字符串（占位符替换为 X）
      router.push('/compare')         JS 调用
      router.push(`/houses/${id}`)    JS 模板字符串
      path: '/overview'               NAV 数组里的入口定义（AppLayout）
    """
    found: dict[str, set[str]] = {}
    files = list(FRONTEND.rglob("*.vue")) + [
        p for p in FRONTEND.rglob("*.js") if p.name != "index.js" or "router" not in str(p)
    ]
    for p in files:
        text = p.read_text(encoding="utf-8")
        targets: set[str] = set()

        patterns = [
            r'(?<!:)to="(/[^"$]*)"',            # to="/x"
            r":to=\"'(/[^']*)'\"",              # :to="'/x'"
            r':to="`(/[^`]*)`"',                # :to="`/x/${id}`"
            r"router\.push\(\s*'(/[^']*)'",     # router.push('/x')
            r"router\.push\(\s*`(/[^`]*)`",     # router.push(`/x/${id}`)
            r"path:\s*'(/[^']*)'",              # NAV: { path: '/x' }
        ]
        for pat in patterns:
            for m in re.finditer(pat, text):
                targets.add(re.sub(r"\$\{[^}]*\}", "X", m.group(1)))

        if targets:
            found[str(p.relative_to(FRONTEND))] = targets
    return found


def main() -> int:
    routes = parse_routes()
    if not routes:
        print("未能解析出路由表", file=sys.stderr)
        return 2

    matchers = [(r, route_regex(r)) for r in routes if "pathMatch" not in r]
    targets = collect_targets()

    dead: list[str] = []
    total = 0
    for file, paths in sorted(targets.items()):
        for path in sorted(paths):
            if "//" in path or path.startswith("/api"):
                continue
            total += 1
            if not any(m.match(path) for _, m in matchers):
                dead.append(f"{file}: {path}")

    check("路由表可解析", len(routes) >= 8, f"共 {len(routes)} 条：{routes}")
    check("所有跳转目标命中路由表", not dead,
          "未匹配：" + "; ".join(dead[:8]) if dead else f"共校验 {total} 个跳转目标")

    # 反向：每个路由都应能从某个入口到达（或被明确标注为详情页）
    reachable = set()
    for paths in targets.values():
        for p in paths:
            for r, m in matchers:
                if m.match(p):
                    reachable.add(r)
    unreachable = [r for r in routes
                   if r not in reachable and "pathMatch" not in r and r != "/"]
    check("每个路由都有入口可到达（无孤立页面）", not unreachable,
          f"无入口：{unreachable}")

    # 侧栏不得出现硬编码 id 的伪入口（历史上出现过 /houses/1 这种）
    layout = (FRONTEND / "layouts" / "AppLayout.vue").read_text(encoding="utf-8")
    hardcoded = re.findall(r"path:\s*'/(?:houses|communities)/\d+'", layout)
    check("侧栏无硬编码 id 入口", not hardcoded, f"发现：{hardcoded}")

    # 404 兜底页存在（GitHub Pages 上旧链接不会直接 404）
    has_404 = (ROOT / "frontend" / "public" / "404.html").exists()
    check("存在 404 兜底页（旧链接自动回首页）", has_404)

    print("=" * 78)
    print("前端跳转目标检查（防死链）")
    print("=" * 78)
    failed = 0
    for i, c in enumerate(checks, 1):
        mark = "OK  " if c["passed"] else "FAIL"
        if not c["passed"]:
            failed += 1
        print(f"[{mark}] {i}. {c['name']}"
              + (f"\n        {c['detail']}" if c["detail"] else ""))
    print("-" * 78)
    print(f"检查结果：{len(checks) - failed}/{len(checks)} 通过（校验 {total} 个跳转目标）")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
