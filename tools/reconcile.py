"""独立对账脚本（不复用 etl 包，仅用标准库重新计算一遍）。

目的：如果对账脚本和 ETL 共用同一份代码，那么"对账通过"只证明代码能重复自己，
不能证明结果正确。本脚本独立读取产物 CSV，用标准库重新计算所有关键指标，
再与 rules.toml 的期望值比对。

用法：
    python tools/reconcile.py                     # 独立复算 + 与期望值对账
    python tools/reconcile.py --record            # 记录当前产物 MD5 为基线
    python tools/reconcile.py --compare           # 与基线比对（可复现性证明）
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TOOLS = ROOT / "tools"
RULES = ROOT / "etl" / "rules.toml"
BASELINE = TOOLS / "baseline.json"

ARTIFACTS = [
    "cleaned_house.csv",
    "cleaned_orientation.csv",
    "dim_district.csv",
    "dim_street.csv",
    "dim_community.csv",
    "quality_report.json",
]

STANDARD_DIRECTIONS = {"东南", "东北", "西南", "西北", "东", "南", "西", "北"}


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def floor_kind(raw: str) -> str:
    """独立实现的楼层形态判定（与 etl.clean 的配置解析互为交叉验证）。"""
    s = (raw or "").strip()
    if re.fullmatch(r"(低|中|高)楼层\(共\d+层\)", s):
        return "labeled"
    if re.fullmatch(r"(顶层|底层)\(共\d+层\)", s):
        return "topbottom"
    if re.fullmatch(r"(上叠|下叠)\(共\d+层\)", s):
        return "stacked"
    if re.fullmatch(r"地下室\(共\d+层\)", s):
        return "basement"
    if re.fullmatch(r"\d+层", s):
        return "pure"
    return "unparsed"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="独立对账 / 可复现性验证")
    ap.add_argument("--record", action="store_true", help="记录当前产物 MD5 为基线")
    ap.add_argument("--compare", action="store_true", help="与基线比对")
    args = ap.parse_args(argv)

    with open(RULES, "rb") as f:
        cfg = tomllib.load(f)
    exp = cfg["expect"]

    if args.record:
        baseline = {name: md5_of(DATA / name) for name in ARTIFACTS}
        BASELINE.write_text(json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8")
        print("已记录基线 →", BASELINE)
        for name, digest in baseline.items():
            print(f"  {name:<26} {digest}")
        return 0

    if args.compare:
        if not BASELINE.exists():
            print("基线文件不存在，请先运行 --record", file=sys.stderr)
            return 2
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        current = {name: md5_of(DATA / name) for name in ARTIFACTS}
        print("=== 可复现性比对（两次运行，逐文件 MD5）===")
        ok = True
        for name in ARTIFACTS:
            same = baseline.get(name) == current[name]
            ok = ok and same
            print(f"  [{'一致' if same else '不一致'}] {name:<26} {current[name]}")
        print()
        print("结论：字节级完全一致，可复现 ✅" if ok else "结论：存在差异 ❌")
        return 0 if ok else 1

    # ---------------- 独立复算 ----------------
    house = read_csv(DATA / "cleaned_house.csv")
    orient = read_csv(DATA / "cleaned_orientation.csv")
    districts = read_csv(DATA / "dim_district.csv")
    streets = read_csv(DATA / "dim_street.csv")
    communities = read_csv(DATA / "dim_community.csv")
    run_meta = json.loads((DATA / "run_meta.json").read_text(encoding="utf-8"))

    area = [float(r["area"]) for r in house]
    total = [float(r["total_price"]) for r in house]
    unit = [float(r["unit_price"]) for r in house]
    age = [float(r["house_age"]) for r in house]

    checks = []

    def check(name, actual, expected, note=""):
        ok = actual == expected
        checks.append({"name": name, "actual": actual, "expected": expected,
                       "passed": ok, "note": note})

    # 1–4 行数与漏斗
    check("主表行数", len(house), exp["loaded_rows"])
    check("朝向表行数", len(orient), exp["orientation_rows"])
    funnel = run_meta["row_funnel"]
    check("行数漏斗自洽", funnel["raw"] == funnel["loaded"] + funnel["rejected"], True,
          f'{funnel["raw"]} = {funnel["loaded"]} + {funnel["rejected"]}')

    # 5–8 维度基���
    check("区数量", len({r["district_id"] for r in house}), exp["districts"])
    check("街道数量", len({r["street_id"] for r in house}), exp["streets"])
    check("小区数量", len({r["community_id"] for r in house}), exp["communities"])
    check("维表行数（区/街道/小区）", [len(districts), len(streets), len(communities)],
          [exp["districts"], exp["streets"], exp["communities"]])

    # 9 维表聚合与主表一致（house_count 求和必须回到 2890）
    check("区维表 house_count 合计", sum(int(r["house_count"]) for r in districts), len(house))
    check("街道维表 house_count 合计", sum(int(r["house_count"]) for r in streets), len(house))
    check("小区维表 house_count 合计", sum(int(r["house_count"]) for r in communities), len(house))

    # 10 外键完整性
    d_ids = {r["district_id"] for r in districts}
    s_ids = {r["street_id"] for r in streets}
    c_ids = {r["community_id"] for r in communities}
    fk_bad = sum(
        1 for r in house
        if r["district_id"] not in d_ids or r["street_id"] not in s_ids
        or r["community_id"] not in c_ids
    )
    check("外键悬空行数", fk_bad, 0)

    # 11 单价公式（独立复算：总价万×10000 ÷ 面积）
    tol = float(cfg["validation"]["unit_price_tolerance"])
    dev = [abs(round(t * 10000.0 / a, 2) - u) for a, t, u in zip(area, total, unit)]
    check("单价公式超容差行数", sum(1 for d in dev if d > tol), exp["unit_price_error_rows"],
          f"最大偏差 {max(dev):.2f} ≤ 容差 {tol}")

    # 12 中位数（statistics.median 对偶数样本取中间两值平均，与线性插值一致）
    check("单价中位数", round(statistics.median(unit), 2), exp["median_unit_price"],
          f'手册上中位数对照 {exp["median_unit_price_upper"]}')
    check("总价中位数", round(statistics.median(total), 2), exp["median_total_price"])
    check("面积中位数", round(statistics.median(area), 2), exp["median_area"],
          f'手册上中位数对照 {exp["median_area_upper"]}')

    # 13 楼层形态独立复算
    kinds: dict[str, int] = {}
    for r in house:
        k = floor_kind(r["floor_raw"])
        kinds[k] = kinds.get(k, 0) + 1
    check("楼层形态计数", {k: kinds.get(k, 0) for k in
                       ["labeled", "topbottom", "pure", "basement", "stacked", "unparsed"]},
          {"labeled": exp["floor_labeled"], "topbottom": exp["floor_topbottom"],
           "pure": exp["floor_pure"], "basement": exp["floor_basement"],
           "stacked": exp["floor_stacked"], "unparsed": exp["floor_unparsed"]})

    # 14 朝向方向合法性
    bad_dir = {r["direction"] for r in orient} - STANDARD_DIRECTIONS
    check("非法朝向方向", sorted(bad_dir), [])
    dup = len(orient) - len({(r["source_row_no"], r["direction"]) for r in orient})
    check("朝向表重复关联行", dup, 0)

    # 15 伪街道（独立统计）：名称数 12，但 (区,街道) 组合 16
    pseudo_streets = [r for r in streets if r["is_pseudo"] == "1"]
    check("伪街道（区,街道）组合数", len(pseudo_streets), exp["pseudo_street_combos"],
          "同一伪街道名出现在多个区，组合数大于名称数")
    check("伪街道名称数", len({r["street_name"] for r in pseudo_streets}),
          exp["pseudo_street_names"])
    check("伪街道覆盖行数", sum(int(r["house_count"]) for r in pseudo_streets),
          exp["pseudo_street_rows"])

    # 16 极值标记
    flagged = sum(1 for r in house if r["is_outlier"] == "1")
    check("极值标记行数", flagged, exp["outlier_flagged_rows"])
    check("极值行是否被删除", len(house), exp["loaded_rows"], "只标记不删除（D7）")

    # 17 source_row_no 完整性（1..N 无缺号）
    row_nos = sorted(int(r["source_row_no"]) for r in house)
    check("行号完整性", row_nos, list(range(1, len(house) + 1)))

    # 18 关键字段无空值
    required = ["district_id", "street_id", "community_id", "room", "hall", "area",
                "total_price", "unit_price", "floor_level", "orientation_text",
                "decoration", "structure", "house_age", "near_subway"]
    empty = {c: sum(1 for r in house if r[c] in ("", None)) for c in required}
    check("关键字段空值数", {k: v for k, v in empty.items() if v}, {})

    # 19 编码：CSV 必须带 BOM（Excel 双击不乱码）
    boms = {name: (DATA / name).read_bytes()[:3] == b"\xef\xbb\xbf"
            for name in ARTIFACTS if name.endswith(".csv")}
    check("CSV 带 UTF-8 BOM", all(boms.values()), True)

    # 20 商品校验：装修/结构在合法枚举内
    valid_deco = {"精装", "简装", "毛坯", "其他"}
    valid_struct = {"板楼", "塔楼", "板塔结合", "独栋别墅", "平房"}
    check("装修取值非法数", sum(1 for r in house if r["decoration"] not in valid_deco), 0)
    check("结构取值非法数", sum(1 for r in house if r["structure"] not in valid_struct), 0)

    # ---------------- 输出 ----------------
    print("=" * 78)
    print("独立对账报告（仅标准库复算，不复用 ETL 代码）")
    print("=" * 78)
    failed = 0
    for i, c in enumerate(checks, 1):
        mark = "OK  " if c["passed"] else "FAIL"
        if not c["passed"]:
            failed += 1
        print(f"[{mark}] {i:>2}. {c['name']}")
        if not c["passed"] or c["note"]:
            print(f"         期望 {c['expected']} / 实测 {c['actual']}"
                  + (f"  — {c['note']}" if c["note"] else ""))
    print("-" * 78)
    print(f"对账结果：{len(checks) - failed}/{len(checks)} 通过")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
