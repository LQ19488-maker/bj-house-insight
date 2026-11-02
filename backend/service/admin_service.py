"""数据导入 / 批次 / 质量报告 / 操作日志 / 健康检查。

导入接口**复用 etl 包**（`etl.clean` / `etl.validate` / `etl.load`）：
命令行跑的与接口跑的是同一份清洗规则，不存在两套逻辑对不齐的可能。
因此本模块对 pandas / openpyxl 有可选依赖（仅在调用导入时要求，纯查询功能不需要）。
"""

from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path

from ..core import db
from ..core.config import get as get_cfg
from ..httpkit.response import ApiError
from ..repository import admin as admin_repo


def health() -> dict:
    cfg = get_cfg()
    info = db.health(cfg.db_path)
    return {
        "status": "ok" if info.get("db") == "up" else "degraded",
        "db": info.get("db"),
        "version": cfg.version,
        "house_rows": info.get("house_rows"),
        "districts": info.get("districts"),
        "communities": info.get("communities"),
        "avg_unit_price": info.get("avg_unit_price"),
        "weighted_unit_price": info.get("weighted_unit_price"),
        "median_total_price": info.get("median_total_price"),
        "readonly": cfg.readonly,
    }


# ---------------------------------------------------------------------------
# 导入
# ---------------------------------------------------------------------------
def _run_pipeline(path: Path) -> dict:
    """复用 ETL 的 R1–R12 全流程，返回内存中的清洗结果（不写库）。"""
    try:
        from etl.clean import (
            apply_r11_pseudo_street,
            apply_r1_strip,
            apply_r1r2_tag_check,
            apply_r2_drop_baseline,
            apply_r3_drop_onehot,
            apply_r4_orientation,
            apply_r5_floor,
            apply_r6_layout,
            apply_r7_numeric,
        )
        from etl.common import IssueLog
        from etl.config import load_rules
        from etl.load import build_dimensions, build_house_frame
        from etl.read import read_raw
        from etl.validate import (build_assertions, mark_outliers, recompute_buckets,
                                  validate_ranges)
    except ImportError as exc:  # pragma: no cover
        raise ApiError(5000, f"导入功能依赖 etl 包或 pandas/openpyxl：{exc}")

    cfg = load_rules()
    log = IssueLog()
    counters: dict = {}

    df, meta = read_raw(path, cfg)
    df.insert(0, "source_row_no", range(1, len(df) + 1))

    df = apply_r1_strip(df, cfg, log, counters)
    df = apply_r1r2_tag_check(df, cfg, log, counters)
    df = apply_r2_drop_baseline(df, cfg, log, counters)
    df = apply_r3_drop_onehot(df, cfg, log, counters)
    df, orient_rows = apply_r4_orientation(df, cfg, log, counters)
    df = apply_r5_floor(df, cfg, log, counters)
    df = apply_r6_layout(df, cfg, log, counters)
    df = apply_r7_numeric(df, cfg, log, counters)
    df = apply_r11_pseudo_street(df, cfg, log, counters)

    reject = validate_ranges(df, cfg, log, counters)
    rejected = int(reject.sum())
    if rejected:
        df = df[~reject].reset_index(drop=True)

    df = mark_outliers(df, cfg, log, counters)
    df = recompute_buckets(df, cfg, log, counters)

    df, dim_district, dim_street, dim_community = build_dimensions(df, cfg, log, counters)
    assertions = build_assertions(df, orient_rows, meta, counters, cfg, rejected_rows=rejected)
    house_df = build_house_frame(df, cfg)

    return {
        "meta": meta, "log": log, "counters": counters, "assertions": assertions,
        "orient_rows": orient_rows, "dim_district": dim_district,
        "dim_street": dim_street, "dim_community": dim_community,
        "house_df": house_df, "rejected": rejected,
    }


def _report_of(pipeline: dict, file_name: str, md5: str, dry_run: bool) -> dict:
    log = pipeline["log"]
    assertions = pipeline["assertions"]
    return {
        "file_name": file_name,
        "file_md5": md5,
        "dry_run": dry_run,
        "total_rows": int(pipeline["meta"]["raw_rows"]),
        "loaded_rows": int(len(pipeline["house_df"])),
        "rejected_rows": int(pipeline["rejected"]),
        "rules_triggered": log.count_by_rule(),
        "issues_total": len(log),
        "assertions": {
            "total": len(assertions),
            "passed": sum(1 for a in assertions if a["passed"]),
            "failed": [a["name"] for a in assertions if not a["passed"]],
        },
        "cardinality": {
            "district": int(pipeline["counters"].get("R10_district_count", 0)),
            "street": int(pipeline["counters"].get("R10_street_count", 0)),
            "community": int(pipeline["counters"].get("R10_community_count", 0)),
            "orientation_rows": int(len(pipeline["orient_rows"])),
        },
    }


def import_excel(filename: str, data: bytes, dry_run: bool,
                 operator_id: int | None) -> dict:
    cfg = get_cfg()
    if not filename.lower().endswith(".xlsx"):
        raise ApiError(4001, "仅支持 .xlsx 文件")
    if len(data) > cfg.max_upload_bytes:
        raise ApiError(4002, f"文件超过 {cfg.max_upload_bytes // 1024 // 1024} MB 上限")
    if cfg.readonly and not dry_run:
        raise ApiError(5000, "当前为只读模式，导入已关闭")

    started = time.perf_counter()
    md5 = hashlib.md5(data).hexdigest()

    cfg.upload_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(tempfile.mkstemp(suffix=".xlsx", dir=str(cfg.upload_dir))[1])
    tmp_path.write_bytes(data)
    try:
        pipeline = _run_pipeline(tmp_path)
        report = _report_of(pipeline, filename, md5, dry_run)

        if dry_run:
            report["batch_id"] = None
            report["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return report

        batch_id = _write_to_db(pipeline, filename, md5, operator_id)
        report["batch_id"] = batch_id
        report["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return report
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _write_to_db(pipeline: dict, file_name: str, md5: str,
                 operator_id: int | None) -> int:
    cfg = get_cfg()
    house_df = pipeline["house_df"]
    counters = pipeline["counters"]

    with db.transaction(cfg.db_path) as con:
        batch_id = admin_repo.batch_create(
            con, file_name, md5, int(pipeline["meta"]["raw_rows"]),
            status="running", operator_id=operator_id)

        # 1) 维度 upsert（返回 etl 维度 id → 库内 id 的映射）
        d_map: dict[int, int] = {}
        for _, r in pipeline["dim_district"].iterrows():
            d_map[int(r["district_id"])] = admin_repo.district_upsert(con, r["district_name"])

        id2dname = {int(r["district_id"]): r["district_name"]
                    for _, r in pipeline["dim_district"].iterrows()}

        s_map: dict[int, int] = {}
        for _, r in pipeline["dim_street"].iterrows():
            etl_did = int(r["district_id"])
            s_map[int(r["street_id"])] = admin_repo.street_upsert(
                con, d_map[etl_did], r["street_name"], int(r["is_pseudo"]))

        c_map: dict[int, int] = {}
        for _, r in pipeline["dim_community"].iterrows():
            etl_did = int(r["district_id"])
            etl_sid = None if r["street_id"] is None or str(r["street_id"]) == "nan" else int(r["street_id"])
            db_sid = s_map.get(etl_sid) if etl_sid is not None else None
            if db_sid is None:
                # 兜底：该小区无街道归属时挂到该区下第一个街道，避免外键悬空
                any_street = con.execute(
                    "SELECT id FROM street WHERE district_id = ? ORDER BY id LIMIT 1",
                    (d_map[etl_did],)).fetchone()
                if any_street is None:
                    raise ApiError(5000, f"区 {id2dname[etl_did]} 下没有街道，无法挂载小区")
                db_sid = int(any_street[0])
            c_map[int(r["community_id"])] = admin_repo.community_upsert(
                con, d_map[etl_did], db_sid, r["community_name"])

        # 2) 主表
        def _i(v):
            return None if v is None or str(v) == "nan" else int(v)

        rows = []
        for r in house_df.itertuples(index=False):
            rows.append((
                d_map[int(r.district_id)], s_map[int(r.street_id)],
                c_map[int(r.community_id)], batch_id, int(r.source_row_no),
                _i(r.room), _i(r.hall), float(r.area), float(r.total_price),
                float(r.unit_price), r.floor_level, _i(r.floor_total), r.floor_raw,
                r.orientation_text, r.decoration, r.structure, _i(r.house_age),
                int(r.near_subway), int(r.is_outlier), int(r.abnormal_layout),
            ))
        admin_repo.houses_insert_many(con, rows)

        # 3) 朝向关联（用 (batch_id, source_row_no) 反查新插入的 id）
        id_of = {
            int(row[0]): int(row[1]) for row in con.execute(
                "SELECT source_row_no, id FROM house WHERE batch_id = ?", (batch_id,))
        }
        orient = []
        for o in pipeline["orient_rows"]:
            hid = id_of.get(int(o["source_row_no"]))
            if hid is not None:
                orient.append((hid, o["direction"]))
        admin_repo.orientation_insert_many(con, orient)

        # 4) 质量问题留痕
        admin_repo.issues_insert_many(con, batch_id, pipeline["log"].records)

        # 5) 刷新维度聚合快照
        admin_repo.refresh_dim_aggregates(con)

        duration = 0
        status = "success"
        admin_repo.batch_finish(con, batch_id, len(rows), int(pipeline["rejected"]),
                                status, duration,
                                note=f"source_row 维度: 区{counters.get('R10_district_count')}"
                                     f" 街道{counters.get('R10_street_count')}"
                                     f" 小区{counters.get('R10_community_count')}")
        admin_repo.log_operation(con, operator_id, "import", "batch", str(batch_id), None, "ok")
    return batch_id


# ---------------------------------------------------------------------------
# 批次与报告
# ---------------------------------------------------------------------------
def batches(page_no: int, size: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        rows, total = admin_repo.batch_list(con, size, (page_no - 1) * size)
    items = [{
        "batch_id": int(r["id"]), "file_name": r["file_name"],
        "total_rows": int(r["total_rows"]), "loaded_rows": int(r["loaded_rows"]),
        "rejected_rows": int(r["rejected_rows"]), "status": r["status"],
        "duration_ms": r["duration_ms"], "created_at": r["created_at"],
        "operator": r["operator"],
    } for r in rows]
    return {"list": items, "total": total, "page": page_no, "page_size": size}


def batch_report(batch_id: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        batch = admin_repo.batch_by_id(con, batch_id)
        if batch is None:
            raise ApiError(3001, f"批次 {batch_id} 不存在")
        rules = admin_repo.rules_triggered(con, batch_id)
        types = admin_repo.issues_by_type(con, batch_id)
        samples, total = admin_repo.issues_by_batch(con, batch_id, 50)

    return {
        "batch": {
            "batch_id": int(batch["id"]), "file_name": batch["file_name"],
            "file_md5": batch["file_md5"], "total_rows": int(batch["total_rows"]),
            "loaded_rows": int(batch["loaded_rows"]),
            "rejected_rows": int(batch["rejected_rows"]),
            "status": batch["status"], "duration_ms": batch["duration_ms"],
            "created_at": batch["created_at"], "note": batch["note"],
        },
        "rules_triggered": rules,
        "issues_by_type": types,
        "issues_total": total,
        "samples": [dict(r) for r in samples],
        "funnel": {
            "raw": int(batch["total_rows"]),
            "loaded": int(batch["loaded_rows"]),
            "rejected": int(batch["rejected_rows"]),
            "self_consistent": int(batch["total_rows"]) == (
                int(batch["loaded_rows"]) + int(batch["rejected_rows"])),
        },
    }


def logs(action: str | None, page_no: int, size: int) -> dict:
    cfg = get_cfg()
    with db.session(cfg.db_path) as con:
        rows, total = admin_repo.list_logs(con, action, size, (page_no - 1) * size)
    return {
        "list": [{"log_id": int(r["id"]), "user_id": r["user_id"], "action": r["action"],
                  "target_type": r["target_type"], "target_id": r["target_id"],
                  "ip": r["ip"], "result": r["result"], "created_at": r["created_at"]}
                 for r in rows],
        "total": total, "page": page_no, "page_size": size,
    }
