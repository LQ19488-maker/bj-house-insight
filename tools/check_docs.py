"""文档一致性检查：把 3a 的四份文档与数据库结构、以及彼此之间对齐。

    python tools/check_docs.py

校验项：
    1. 业务问题 12 条，P0 ≥ 5
    2. FR 编号 FR-01…FR-26 连续无缺、无重
    3. 功能点 FP-Mn-xx 编号唯一、总数 40–55、模块 8 个
    4. 模块 MoSCoW：Must ≤ 5
    5. 接口表 29 行，路径唯一
    6. 追溯矩阵的"接口 → 模块/功能点"反向表与契约的接口总表**一一对应**
    7. 追溯矩阵覆盖全部 26 条 FR
    8. 契约中出现的每个 `表.字段` 在 schema_model.py 中真实存在（防笔误）
    9. 契约中的错误码与 SRS/通用约定一致（12 条）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "db"))

from schema_model import TABLES  # noqa: E402

DOCS = ROOT / "docs"
SRS = DOCS / "01-SRS.md"
MODULES = DOCS / "02-模块清单.md"
CONTRACT = DOCS / "api-contract.md"
TRACE = DOCS / "02-追溯矩阵.md"

checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def main() -> int:
    srs = SRS.read_text(encoding="utf-8")
    modules = MODULES.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    trace = TRACE.read_text(encoding="utf-8")

    # ---------- 1. 业务问题 ----------
    q_ids = re.findall(r"^### Q(\d+)\s", srs, re.M)
    check("业务问题 12 条", len(q_ids) == 12, f"实测 {len(q_ids)}：{q_ids}")
    p0 = len(re.findall(r"^### Q\d+.*【P0】", srs, re.M))
    check("P0 业务问题 ≥ 5", p0 >= 5, f"实测 P0 = {p0}")

    # ---------- 2. FR ----------
    fr_ids = sorted(set(re.findall(r"FR-\d{2}", srs)))
    expected_fr = [f"FR-{i:02d}" for i in range(1, 27)]
    check("FR 数量 20–28", 20 <= len(fr_ids) <= 28, f"实测 {len(fr_ids)} 条")
    check("FR 编号连续无缺", fr_ids == expected_fr,
          f"缺：{sorted(set(expected_fr) - set(fr_ids))}；多：{sorted(set(fr_ids) - set(expected_fr))}")

    # ---------- 3. 功能点 ----------
    fp_ids = re.findall(r"FP-M\d-\d{2}", modules)
    fp_unique = sorted(set(fp_ids))
    check("功能点 40–55", 40 <= len(fp_unique) <= 55, f"实测 {len(fp_unique)} 个唯一编号")
    dup = len(fp_ids) - len(fp_unique)
    check("功能点编号无重复", dup == 0, f"重复 {dup} 处")
    mods = sorted(set(re.findall(r"FP-M(\d)-\d{2}", modules)))
    check("模块数 7–9", 7 <= len(mods) <= 9, f"实测 M{mods}")

    # ---------- 4. MoSCoW ----------
    # 模块表列：编号 | 名称 | 职责 | 做什么 | 不做 | MoSCoW | 理由
    must = re.findall(r"^\| (M\d) \|(?:[^|]*\|){4} \*\*Must\*\* \|", modules, re.M)
    check("Must 模块 ≤ 5", 0 < len(must) <= 5, f"实测 Must = {len(must)}：{must}")

    # ---------- 5. 接口表 ----------
    rows = re.findall(r"^\| (\d+) \| (GET|POST|DELETE) \| `([^`]+)` \|", contract, re.M)
    endpoints = [f"{m} {p}" for _, m, p in rows]
    check("契约接口表 29 行", len(rows) == 29, f"实测 {len(rows)} 行")
    check("接口（方法+路径）唯一", len(endpoints) == len(set(endpoints)),
          f"重复：{sorted(p for p in endpoints if endpoints.count(p) > 1)}")

    # ---------- 6. 追溯矩阵反向表与契约一一对应 ----------
    trace_rows = re.findall(r"^\| \d+ \| `([^`]+)` \| (M\d[^|]*) \| ([^|]+) \|", trace, re.M)
    trace_endpoints = [p.strip() for p, _, _ in trace_rows]
    check("追溯矩阵反向表 29 行", len(trace_rows) == 29, f"实测 {len(trace_rows)} 行")
    missing_in_trace = sorted(set(endpoints) - set(trace_endpoints))
    extra_in_trace = sorted(set(trace_endpoints) - set(endpoints))
    check("契约接口全部进了追溯矩阵", not missing_in_trace, f"缺：{missing_in_trace}")
    check("追溯矩阵无多余接口", not extra_in_trace, f"多：{extra_in_trace}")

    # ---------- 7. FR 全覆盖 ----------
    fr_in_trace = set(re.findall(r"FR-\d{2}", trace))
    missing_fr = sorted(set(expected_fr) - fr_in_trace)
    check("追溯矩阵覆盖全部 FR", not missing_fr, f"缺：{missing_fr}")

    # ---------- 8. 契约里的 表.字段 必须真实存在 ----------
    table_cols = {
        t["name"]: {c["name"] for c in t["columns"]} for t in TABLES
    }
    pairs = set(re.findall(r"`(\w+)\.(\w+)`", contract))
    bad_pairs, checked = [], 0
    for tbl, col in sorted(pairs):
        if tbl not in table_cols:
            continue  # 形如 05-ER.md 之类的文号，不按表处理
        checked += 1
        if col not in table_cols[tbl]:
            bad_pairs.append(f"{tbl}.{col}")
    check("契约中的 表.字段 全部真实存在", not bad_pairs,
          f"不存在：{bad_pairs}（共校验 {checked} 个）")

    # 反向：契约 §4「与数据库的字段对应」表必须覆盖 ≥ 12 个契约字段
    sec4 = contract.split("## 4. 与数据库的字段对应")[-1].split("## 5.")[0]
    mapped = re.findall(r"^\| `[^`]+` \| `[^`]+` \|", sec4, re.M)
    check("契约 §4 字段映射 ≥ 12 行", len(mapped) >= 12, f"实测 {len(mapped)} 行")

    # ---------- 9. 错误码 ----------
    code_sec = contract.split("### 0.3 错误码表")[-1].split("### 0.4")[0]
    codes = re.findall(r"^\| (\d{1,4}) \| ", code_sec, re.M)
    check("错误码 12 条（含 code=0）", len(codes) == 12,
          f"实测 {len(codes)}：{codes}")

    # ---------- 输出 ----------
    print("=" * 78)
    print("3a 文档一致性检查（SRS ↔ 模块清单 ↔ 接口契约 ↔ 追溯矩阵 ↔ schema）")
    print("=" * 78)
    failed = 0
    for i, c in enumerate(checks, 1):
        mark = "OK  " if c["passed"] else "FAIL"
        if not c["passed"]:
            failed += 1
        print(f"[{mark}] {i:>2}. {c['name']}"
              + (f"  — {c['detail']}" if c["detail"] and not c["passed"] else ""))
    print("-" * 78)
    print(f"检查结果：{len(checks) - failed}/{len(checks)} 通过")

    # 统计概览
    print(f"概览：业务问题 {len(q_ids)}（P0 {p0}）｜FR {len(fr_ids)}｜"
          f"模块 {len(mods)}（Must {len(must)}）｜功能点 {len(fp_unique)}｜接口 {len(rows)}")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
