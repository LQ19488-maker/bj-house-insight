"""配置加载与路径约定。

手册建议 rules.yaml；本项目使用 rules.toml —— Python 3.11+ 标准库 tomllib
可直接解析，无需安装 PyYAML，与"零运行时依赖"的整体设计一致。
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

ETL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ETL_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DOCS_DIR = PROJECT_ROOT / "docs"
DEFAULT_RULES = ETL_DIR / "rules.toml"


def load_rules(path: Path | str = DEFAULT_RULES) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def md5_of(path: Path | str, chunk_size: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def find_input(raw_dir: Path | str = RAW_DIR) -> Path:
    """定位原始数据文件；必须唯一，防止误读多个数据源。"""
    raw_dir = Path(raw_dir)
    files = sorted(p for p in raw_dir.glob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        raise FileNotFoundError(f"{raw_dir} 下未找到 xlsx 数据文件")
    if len(files) > 1:
        names = [p.name for p in files]
        raise RuntimeError(f"{raw_dir} 下存在多个 xlsx，请只保留一份：{names}")
    return files[0]
