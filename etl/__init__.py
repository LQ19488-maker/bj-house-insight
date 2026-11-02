"""北京二手房数据 ETL 管道。

模块划分（对应手册第 8 步）：
    read      读取原始 Excel，记录可复现元信息（MD5 / 版本）
    clean     R1–R7 / R11–R12：清洗与标准化
    validate  R7 数值校验、R8 极值标记、R9 分桶复算、断言
    load      R10 维度构建 + 产物落盘（CSV / run_meta）
    report    质量报告（JSON + 人读 Markdown）
    run       单入口编排
"""

__all__ = ["config", "common", "read", "clean", "validate", "load", "report", "run"]
__version__ = "1.0.0"
