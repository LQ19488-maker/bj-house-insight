"""分层静态检查：把"三层架构"从口号变成可跑出绿勾的检查项。

    python tools/check_layers.py

手册步骤十要求"抽查 handler 有无 SQL"。人工抽查一次只能看一个文件，
本脚本把这条要求变成对全部分层的自动化检查。

规则：
    L1  api/handler/** 不得出现 SQL 关键字或 execute(
    L2  service/** 不得 import httpkit 的 ctx/router/multipart/static/middleware
        （只允许 import ApiError —— 业务异常本身需要携带错误码）
    L3  service/** 不得出现 HTTP 相关字样（status_code / self.headers / wfile）
    L4  repository/** 不得 import service 或 api；不得出现业务阈值关键字
    L5  只有 repository/** 与 core/db.py 可以 import sqlite3
    L6  反向依赖：service 不得 import api；repository 不得 import api/service
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

SQL_KEYWORDS = re.compile(
    r"\b(SELECT\s+|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE)\b",
    re.IGNORECASE)
HTTP_LEAK = re.compile(r"\b(status_code|self\.headers|wfile|BaseHTTPRequestHandler|"
                       r"send_response)\b")
BIZ_THRESHOLD = re.compile(r"\b(SAMPLE_MIN|FALLBACK_MIN|confidence|insufficient_sample|"
                           r"readonly)\b")

checks: list[dict] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def py_files(sub: str) -> list[Path]:
    return sorted((BACKEND / sub).rglob("*.py"))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    """去掉注释与文档字符串，避免把说明文字误判为违规代码。"""
    text = re.sub(r'""".*?"""', "", text, flags=re.S)
    text = re.sub(r"'''.*?'''", "", text, flags=re.S)
    text = re.sub(r"#.*", "", text)
    return text


def imports_of(text: str) -> list[str]:
    out = []
    for m in re.finditer(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", text, re.M):
        out.append(m.group(1) or m.group(2))
    return out


# ---------------------------------------------------------------------------
def main() -> int:
    # L1 handler 不许有 SQL
    offenders = []
    for p in py_files("api/handler"):
        code = strip_comments(read(p))
        if SQL_KEYWORDS.search(code) or "execute(" in code:
            offenders.append(p.name)
    check("L1 handler 层无 SQL", not offenders, f"违规文件：{offenders}")

    # L2 service 不许 import 框架内部
    allowed_httpkit = {"ApiError"}   # 业务异常可携带错误码
    offenders = []
    for p in py_files("service"):
        code = strip_comments(read(p))
        for m in re.finditer(r"from\s+\.\.httpkit\.(\w+)\s+import\s+([^\n]+)", code):
            module, names = m.group(1), m.group(2)
            if module == "response" and all(
                    n.strip() in allowed_httpkit for n in names.split(",") ):
                continue
            offenders.append(f"{p.name} → httpkit.{module}")
        if re.search(r"from\s+\.\.httpkit\s+import\s+(?!response)", code):
            offenders.append(f"{p.name} → httpkit 包")
    check("L2 service 层不依赖 Web 框架上下文", not offenders, "；".join(offenders))

    # L3 service 不得出现 HTTP 字样
    offenders = []
    for p in py_files("service"):
        code = strip_comments(read(p))
        hit = HTTP_LEAK.search(code)
        if hit:
            offenders.append(f"{p.name}:{hit.group(0)}")
    check("L3 service 层无 HTTP 泄漏", not offenders, "；".join(offenders))

    # L4 repository 不得 import service/api，且不含业务阈值
    offenders = []
    for p in py_files("repository"):
        text = read(p)
        code = strip_comments(text)
        for imp in imports_of(code):
            if "service" in imp or ".api" in imp or imp.endswith("api"):
                offenders.append(f"{p.name} → {imp}")
        hit = BIZ_THRESHOLD.search(code)
        if hit:
            offenders.append(f"{p.name}:业务阈值 {hit.group(0)}")
    check("L4 repository 层只做数据访问", not offenders, "；".join(offenders))

    # L5 只有 repository 与 core/db.py 能 import sqlite3
    offenders = []
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).as_posix()
        if rel.startswith("repository/") or rel == "core/db.py":
            continue
        if re.search(r"^\s*import\s+sqlite3", strip_comments(read(p)), re.M):
            offenders.append(rel)
    check("L5 sqlite3 只在 repository 与 core/db.py 出现", not offenders,
          f"违规文件：{offenders}")

    # L6 反向依赖
    offenders = []
    for p in py_files("service"):
        for imp in imports_of(strip_comments(read(p))):
            if ".api" in imp or imp.startswith("backend.api"):
                offenders.append(f"service/{p.name} → {imp}")
    for p in py_files("repository"):
        for imp in imports_of(strip_comments(read(p))):
            if "service" in imp or "backend.api" in imp:
                offenders.append(f"repository/{p.name} → {imp}")
    check("L6 无反向依赖", not offenders, "；".join(offenders))

    # 附加：分层文件清单（证明三层都真实存在且非空）
    counts = {
        "api/handler": len([p for p in py_files("api/handler") if p.name != "__init__.py"]),
        "service": len([p for p in py_files("service") if p.name != "__init__.py"]),
        "repository": len([p for p in py_files("repository") if p.name != "__init__.py"]),
        "dto": len([p for p in py_files("dto") if p.name != "__init__.py"]),
        "model": len([p for p in py_files("model") if p.name != "__init__.py"]),
        "httpkit": len([p for p in py_files("httpkit") if p.name != "__init__.py"]),
        "core": len([p for p in py_files("core") if p.name != "__init__.py"]),
    }
    check("三层目录均为非空（handler/service/repository）",
          all(counts[k] > 0 for k in ("api/handler", "service", "repository")),
          str(counts))

    # 附加：service 不直接持有 sqlite3 连接类型注解（连接只在 repository 出现）
    offenders = []
    for p in py_files("service"):
        if re.search(r"sqlite3\.Connection", strip_comments(read(p))):
            offenders.append(p.name)
    check("L7 service 不暴露 sqlite3 连接类型", not offenders, "；".join(offenders))

    # ---------- 输出 ----------
    print("=" * 78)
    print("分层静态检查（替代人工抽查 handler 有没有 SQL）")
    print("=" * 78)
    failed = 0
    for i, c in enumerate(checks, 1):
        mark = "OK  " if c["passed"] else "FAIL"
        if not c["passed"]:
            failed += 1
        print(f"[{mark}] {i}. {c['name']}"
              + (f"\n        {c['detail']}" if c["detail"] else ""))
    print("-" * 78)
    print(f"检查结果：{len(checks) - failed}/{len(checks)} 通过")
    print(f"文件分布：{counts}")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
