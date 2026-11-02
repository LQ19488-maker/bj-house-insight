"""单入口编排：python -m etl.run

用法：
    python -m etl.run                          # 默认：data/raw/*.xlsx → data/ + docs/
    python -m etl.run --input <xlsx> --out data --report data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许 `python etl/run.py` 与 `python -m etl.run` 两种调用方式
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.clean import (  # noqa: E402
    apply_r1r2_tag_check,
    apply_r1_strip,
    apply_r2_drop_baseline,
    apply_r3_drop_onehot,
    apply_r4_orientation,
    apply_r5_floor,
    apply_r6_layout,
    apply_r7_numeric,
    apply_r11_pseudo_street,
)
from etl.common import IssueLog  # noqa: E402
from etl.config import (  # noqa: E402
    DATA_DIR,
    DOCS_DIR,
    DEFAULT_RULES,
    find_input,
    load_rules,
)
from etl.load import build_dimensions, build_house_frame, write_outputs  # noqa: E402
from etl.read import read_raw  # noqa: E402
from etl.report import build_quality_report, write_report  # noqa: E402
from etl.validate import (  # noqa: E402
    build_assertions,
    mark_outliers,
    recompute_buckets,
    validate_ranges,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="北京二手房数据 ETL 管道")
    parser.add_argument("--input", default=None, help="原始 xlsx 路径（默认 data/raw 下唯一文件）")
    parser.add_argument("--rules", default=str(DEFAULT_RULES), help="规则配置 rules.toml")
    parser.add_argument("--out", default=str(DATA_DIR), help="产物目录（默认 data/）")
    parser.add_argument("--report", default=str(DATA_DIR), help="质量报告 JSON 目录（默认 data/）")
    parser.add_argument("--docs", default=str(DOCS_DIR), help="人读报告目录（默认 docs/）")
    parser.add_argument("--quiet", action="store_true", help="只打印结论")
    args = parser.parse_args(argv)

    cfg = load_rules(args.rules)
    cfg["meta"]["rules_version"] = cfg["meta"]["rules_version"]
    xlsx = Path(args.input) if args.input else find_input()
    out_dir = Path(args.out)
    report_dir = Path(args.report)
    docs_dir = Path(args.docs)

    log = IssueLog()
    counters: dict = {}
    meta_extra = {"rules_version": cfg["meta"]["rules_version"]}

    def banner(text):
        if not args.quiet:
            print(f"\n=== {text} ===")

    banner("R0 读取原始数据")
    df, meta = read_raw(xlsx, cfg)
    meta.update(meta_extra)
    raw_df = df.copy()
    # 行号列：1 基，对应 Excel 数据行（不含表头），用于全程留痕与回溯
    df.insert(0, "source_row_no", range(1, len(df) + 1))
    print(f"读取：{meta['input_file']}  {meta['raw_rows']} 行 × {meta['raw_cols']} 列")
    print(f"MD5 ：{meta['input_md5']}")

    banner("R1 去除首尾空格")
    df = apply_r1_strip(df, cfg, log, counters)
    print(f"受影响单元格：{counters['R1_changed_total']}")

    banner("R12 房源标签交叉校验（须在丢弃 one-hot 之前）")
    df = apply_r1r2_tag_check(df, cfg, log, counters)
    print(f"标签与 one-hot 不一致：{counters['R12_tag_vs_onehot_diff']}")

    banner("R2 丢弃装修冗余基线列")
    df = apply_r2_drop_baseline(df, cfg, log, counters)
    print(f"列 `{counters['R2_redundant_baseline_column']}` 已丢弃，"
          f"命中 {counters['R2_redundant_baseline_true_rows']} 行")

    banner("R3 丢弃 36 个 one-hot 列")
    df = apply_r3_drop_onehot(df, cfg, log, counters)
    print(f"丢弃列数：{counters['R3_dropped_count']}")

    banner("R4 朝向拆分")
    df, orient_rows = apply_r4_orientation(df, cfg, log, counters)
    print(f"多值房源：{counters['R4_multi_value_rows']} 条　关联行数：{counters['R4_orientation_rows']}")

    banner("R5 楼层解析")
    df = apply_r5_floor(df, cfg, log, counters)
    print(f"形态分布：{counters['R5_floor_kind_counts']}")

    banner("R6 户型解析")
    df = apply_r6_layout(df, cfg, log, counters)
    print(f"户型 {counters['R6_layout_variety']} 种；异常组合 {counters['R6_abnormal_layout_rows']} 条；"
          f"室/厅不一致 {counters['R6_room_mismatch']}/{counters['R6_hall_mismatch']}")

    banner("R7 数值转换与单价一致性")
    df = apply_r7_numeric(df, cfg, log, counters)
    print(f"单价最大偏差 {counters['R7_unit_price_max_dev']} 元/㎡；"
          f"超容差行数 {counters['R7_unit_price_dev_gt_tolerance']}")

    banner("R11 伪街道标记")
    df = apply_r11_pseudo_street(df, cfg, log, counters)
    print(f"伪街道 {counters['R11_pseudo_street_name_count']} 个，覆盖 {counters['R11_pseudo_street_rows']} 行")

    banner("R7 范围校验")
    reject = validate_ranges(df, cfg, log, counters)
    print(f"拒收行数：{counters['R7_reject_rows']}")
    if int(reject.sum()):
        df = df[~reject].reset_index(drop=True)

    banner("R8 极值标记（只标记不删除）")
    df = mark_outliers(df, cfg, log, counters)
    print(f"标记行数：{counters['R8_outlier_rows']}　删除行数：{counters['R8_deleted_rows']}")

    banner("R9 区间口径复算")
    df = recompute_buckets(df, cfg, log, counters)
    for k, v in counters["R9_bucket_check"].items():
        print(f"{k}: 口径={v['convention']} 匹配 {v['matched_rows']}/{v['compared_rows']}"
              f"（原始缺失 {v['src_null_rows']}）")

    banner("R10 维度构建")
    df, dim_district, dim_street, dim_community = build_dimensions(df, cfg, log, counters)
    print(f"区 {counters['R10_district_count']}　街道 {counters['R10_street_count']}"
          f"（街道名去重 {counters['R10_street_name_only_count']}）"
          f"　小区 {counters['R10_community_count']}")

    banner("断言校验")
    meta["rules_version"] = cfg["meta"]["rules_version"]
    assertions = build_assertions(
        df, orient_rows, meta, counters, cfg, rejected_rows=int(meta["raw_rows"] - len(df))
    )
    failed = [a for a in assertions if not a["passed"]]
    for a in assertions:
        mark = "OK  " if a["passed"] else "FAIL"
        print(f"[{mark}] {a['name']}: 期望 {a['expected']} / 实测 {a['actual']}"
              + (f"  ({a['note']})" if a.get("note") else ""))

    banner("产物落盘")
    house = build_house_frame(df, cfg)
    write_info = write_outputs(
        out_dir, house, orient_rows, dim_district, dim_street, dim_community,
        meta, counters, assertions, issues=log.records,
    )
    for name, digest in write_info["artifacts"].items():
        print(f"{name:<26} rows={write_info['run_meta']['outputs']['rows'][name]:>5}  md5={digest}")

    banner("质量报告")
    report = build_quality_report(raw_df, df, meta, counters, assertions, log, cfg)
    paths = write_report(report, report_dir, docs_dir)
    for name, p in paths.items():
        print(f"{name:<22} → {p}")

    print("\n" + "=" * 72)
    if failed:
        print(f"结果：{len(assertions) - len(failed)}/{len(assertions)} 断言通过，"
              f"{len(failed)} 条失败 → {[a['name'] for a in failed]}")
        print("=" * 72)
        return 1
    print(f"结果：{len(assertions)}/{len(assertions)} 断言全部通过，产物已生成。")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
