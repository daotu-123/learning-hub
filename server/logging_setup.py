# -*- coding: utf-8 -*-
"""访问日志脱敏（M1a-D）。

背景（基线 §8-g）：`LOG_CONFIG` 没定义 `uvicorn.access` logger，access 日志走 root
handler，消息由 uvicorn 内部拼成 `client - "METHOD /path?query HTTP/1.1" status`，
**query string 原样落盘**。于是 `?token=<访问令牌>` 会明文写进 server.log
（2MB×3 轮转），而 Gate 0 §0.7 明确要求"不在日志中保留明文令牌"。

做法：给 root handler 挂一个 `logging.Filter`，在记录落盘前改写 query。
不换成自定义 formatter，因为 **query 在 `record.args` 里而不是 `record.msg` 里**
（uvicorn 用 `logger.info('%s - "%s" %d', addr, request_line, status)` 惰性格式化），
只处理 msg 的 formatter 会漏掉真正含令牌的那一段。
"""
import logging
import re
from pathlib import Path

# 命中 ?token=xxx / &token=xxx / 裸 token=xxx，以及同样形状的 sig。
# 前面加负向回顾 (?<![A-Za-z0-9_])：避免把 my_token 这类自定义参数名误伤，
# 同时 ?/&/字符串开头/引号后都能命中。
_SENSITIVE_QUERY = re.compile(
    r"(?<![A-Za-z0-9_])(?:token|sig)=[^&\s\"'<>\\]*", re.IGNORECASE
)

MASK = "***"


def mask_query(text: str) -> str:
    """把 query 里的 token/sig 值打码。幂等：重复调用结果不变。"""
    if not text:
        return text
    return _SENSITIVE_QUERY.sub(lambda m: m.group(0).split("=", 1)[0] + "=" + MASK, text)


class SensitiveQueryFilter(logging.Filter):
    """落盘前改写日志里的 query 串。

    两步走：
      1) 按结构改 record.msg / record.args（保持日志可读，只动敏感值）；
      2) 兜底再对**格式化后的整条消息**打一次码——因为有些库把 URL 以非 str 对象
         放进 args（实测 httpx 传的是 httpx.URL），第 1 步按 isinstance(str) 会漏掉，
         而格式化发生在 handler emit 时，届时已经来不及拦。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_query(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(
                mask_query(a) if isinstance(a, str) else a for a in args
            )
        elif isinstance(args, dict):
            record.args = {
                k: (mask_query(v) if isinstance(v, str) else v) for k, v in args.items()
            }

        try:
            full = record.getMessage()
        except Exception:
            return True
        masked = mask_query(full)
        if masked != full:
            # 用已打码的整条消息替换，args 置空避免二次 % 格式化
            record.msg = masked
            record.args = None
        return True


def build_log_config(
    log_file: Path,
    max_bytes: int = 2 * 1024 * 1024,
    backup_count: int = 2,
) -> dict:
    """构造 uvicorn 的 log_config。

    与改前逐字一致的项：root logger、INFO 级别、RotatingFileHandler、2MB×3、
    utf-8、`%(asctime)s %(levelname)s %(message)s` 格式。
    唯一新增：handler 上的 `filters: ["mask"]`。
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"f": {"format": "%(asctime)s %(levelname)s %(message)s"}},
        "filters": {"mask": {"()": SensitiveQueryFilter}},
        "handlers": {
            "h": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log_file),
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8",
                "formatter": "f",
                "filters": ["mask"],
            }
        },
        "root": {"level": "INFO", "handlers": ["h"]},
    }
