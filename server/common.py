# -*- coding: utf-8 -*-
"""跨 router 共享的"非鉴权"基础设施。

放什么：settings 读写、文件/路径工具、时间与格式化。
**不放**：auth_token / _loopback / AUTH_EXEMPT_API —— 那三样是鉴权代码，
按 M1b-2 的要求留在 main.py，不许搬进来（避免鉴权逻辑散落多个文件）。

约束：本模块不许 import main，也不许 import routers/*（否则必成环）。
"""
import datetime
import json
from pathlib import Path
from typing import Optional

from config import DATA_DIR

SETTINGS_JSON = DATA_DIR / "settings.json"


# ---------------------------------------------------------------- settings
def get_settings() -> dict:
    """读全局 settings.json；损坏或不存在时返回空 dict（与原实现一致）。"""
    if SETTINGS_JSON.exists():
        try:
            return json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(patch: dict) -> dict:
    """合并写入 settings.json（浅合并，与原实现一致）。"""
    s = get_settings()
    s.update(patch)
    SETTINGS_JSON.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return s


# ---------------------------------------------------------------- 时间与格式化
def utc_to_local(dt_str: str) -> Optional[datetime.datetime]:
    """把带时区的 ISO 时间转成本地 datetime；失败返回 None。"""
    if not dt_str:
        return None
    s = dt_str.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.replace(tzinfo=None)
    except Exception:
        return None


def today_iso() -> str:
    """Query(default_factory=...) 用的今天日期。"""
    return datetime.date.today().isoformat()


def month_dir_name(d: datetime.date) -> str:
    """Obsidian 日记月份目录名，如 26年10月。"""
    return f"{str(d.year)[2:]}年{d.month}月"


def md5_text(text: str) -> str:
    """内容指纹（日记/文档同步冲突检测用）。"""
    import hashlib

    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 文件/文本工具
def parse_frontmatter(text: str) -> dict:
    """解析 markdown 前部的 YAML frontmatter（只支持扁平 key: value）。"""
    import re

    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        meta[k] = v
    return meta


def read_head(p: Path, size: int = 2048) -> str:
    """只读文件头（覆盖 frontmatter），避免全量读大文件。"""
    try:
        with open(p, "rb") as fh:
            raw = fh.read(size)
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def touch_modified(text: str) -> str:
    """更新 frontmatter dateModified 字段（Obsidian Tasks 插件约定）。"""
    import re

    now = datetime.datetime.now().isoformat(timespec="milliseconds") + "+08:00"
    if re.search(r"^dateModified:.*$", text, flags=re.M):
        return re.sub(r"^dateModified:.*$", f"dateModified: {now}", text, count=1, flags=re.M)
    return text
