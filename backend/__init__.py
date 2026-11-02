"""北京二手房行情洞察系统 · 后端（零第三方依赖，仅标准库 + sqlite3）。

分层（依赖方向单向，禁止反向）：

    api/handler  →  service  →  repository  →  core.db
         ↓            ↓            ↓
        dto         model        model

    httpkit     手写框架层（路由 / 上下文 / 统一响应 / 中间件 / multipart / 静态托管）
    core        配置 / 数据库 / 安全（PBKDF2 + JWT）

`tools/check_layers.py` 会静态检查分层是否被破坏。
"""

__all__ = ["httpkit", "core", "model", "dto", "repository", "service", "api"]
