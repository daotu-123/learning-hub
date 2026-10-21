# -*- coding: utf-8 -*-
"""收藏库（抖音 / 小红书）扫描 + 当日聚合（M1b-2 从 main.py 拆出）。

路由：
    GET /api/favorites   当日收藏（可按 platform 过滤）
    GET /api/summary     当日聚合：收藏 + DeepTutor + 日记 + 使用统计

`/api/summary` 按 owner 决定归到本域（基线里的"聚合"语义），
**响应字段一个都没动**，只是换了个文件放。

启动副作用（原 main.py 的 @app.on_event("startup")）也在这里：
    load_index_on_start() + background_refresh()
main.py 的 startup 钩子改成调用这两个导出函数。
"""
import json
import threading
import time

from fastapi import APIRouter, Query

from common import parse_frontmatter, read_head, today_iso, utc_to_local
from config import DATA_DIR, FAVORITES_ROOT, OBSIDIAN_VAULT
from routers.docs import deeptutor_daily, deeptutor_notes, diary_sync_state

router = APIRouter(tags=["favorites"])

DOUYIN_DIR = OBSIDIAN_VAULT / "抖音收藏"
XHS_DIR = FAVORITES_ROOT / "小红书收藏"

_cache = {"ts": 0.0, "data": None}
CACHE_TTL = 120.0   # 秒
INDEX_JSON = DATA_DIR / "favorites_index.json"
SCAN_LOCK = threading.Lock()


def scan_favorites(force: bool = False) -> dict:
    """扫描抖音 + 小红书收藏, 返回 {date: {platform: [items]}}; 带持久化缓存"""
    now = time.time()
    if not force and _cache["data"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["data"]
    with SCAN_LOCK:
        # 双检: 等待锁期间可能已被刷新
        if not force and _cache["data"] and now - _cache["ts"] < CACHE_TTL:
            return _cache["data"]
        result = {}

        def add_item(date_key, platform, item):
            result.setdefault(date_key, {}).setdefault(platform, []).append(item)

        # 抖音: 抖音收藏/{主题}/*.md  frontmatter.observed_at (UTC)
        if DOUYIN_DIR.exists():
            for f in DOUYIN_DIR.glob("*/*.md"):
                text = read_head(f)
                meta = parse_frontmatter(text)
                dt = utc_to_local(meta.get("observed_at", ""))
                if dt is None:
                    continue
                date_key = dt.strftime("%Y-%m-%d")
                add_item(date_key, "douyin", {
                    "id": meta.get("aweme_id", f.stem),
                    "title": meta.get("title", f.stem)[:120],
                    "author": meta.get("author", ""),
                    "url": meta.get("source_url", ""),
                    "collected_at": dt.isoformat(timespec="seconds"),
                    "category": f.parent.name,
                    "note_path": str(f).replace(str(OBSIDIAN_VAULT), "").lstrip("\\/"),
                })

        # 小红书: 小红书收藏/{一级}/{二级}/*.md  frontmatter.collected_at (本地时区)
        if XHS_DIR.exists():
            for f in XHS_DIR.glob("*/*/*.md"):
                text = read_head(f)
                meta = parse_frontmatter(text)
                dt = utc_to_local(meta.get("collected_at", ""))
                if dt is None:
                    continue
                date_key = dt.strftime("%Y-%m-%d")
                add_item(date_key, "xiaohongshu", {
                    "id": meta.get("note_id", f.stem),
                    "title": meta.get("title", f.stem)[:120],
                    "author": meta.get("author", ""),
                    "url": meta.get("url", ""),
                    "collected_at": dt.isoformat(timespec="seconds"),
                    "category": meta.get("category", f.parent.parent.name),
                    "subcategory": meta.get("subcategory", f.parent.name),
                    "note_path": str(f).replace(str(XHS_DIR), "").lstrip("\\/"),
                })

        _cache["ts"] = now
        _cache["data"] = result
        try:
            INDEX_JSON.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return result


def load_index_on_start() -> dict:
    """启动时加载持久化索引, 避免冷启动全量扫描阻塞"""
    if INDEX_JSON.exists():
        try:
            data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
            _cache["data"] = data
            _cache["ts"] = time.time()
            return data
        except Exception:
            pass
    return {}


def background_refresh(interval: float = 300.0):
    """后台线程: 每 interval 秒全量重扫一次收藏"""
    while True:
        try:
            time.sleep(interval)
            scan_favorites(force=True)
        except Exception:
            time.sleep(30)


def _usage_day_counts(date_str: str):
    """当日 usage 表的条数与总时长（summary 用，复用 usage 域的连接逻辑）。

    必须走 usage_db.connect()：它保证表已建。这里原来是裸
    `sqlite3.connect(USAGE_DB)`，**不建表**——首启（空数据目录）时
    `SELECT ... FROM usage` 直接抛 `no such table: usage`，把 /api/summary
    打成 500。而只要先访问过一次 /api/usage，表就被它的连接函数建出来，
    同一个接口又恢复 200：**行为取决于请求顺序**，极难排查。
    """
    import sqlite3

    import usage_db

    con = usage_db.connect()
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(day_ms),0) AS ms FROM usage WHERE date=?",
        (date_str,)).fetchone()
    con.close()
    return row["n"], row["ms"]


@router.get("/api/favorites")
def favorites(date: str = Query(default_factory=today_iso),
              platform: str = None):
    favs = scan_favorites()
    day_favs = favs.get(date, {})
    if platform:
        return {"date": date, "platform": platform, "items": day_favs.get(platform, [])}
    return {"date": date, "douyin": day_favs.get("douyin", []),
            "xiaohongshu": day_favs.get("xiaohongshu", [])}


@router.get("/api/summary")
def summary(date: str = Query(default_factory=today_iso)):
    favs = scan_favorites()
    day_favs = favs.get(date, {})
    dt = deeptutor_daily(date)
    ds = diary_sync_state(date)
    n, ms = _usage_day_counts(date)
    return {
        "date": date,
        "favorites": {
            "douyin": len(day_favs.get("douyin", [])),
            "xiaohongshu": len(day_favs.get("xiaohongshu", [])),
        },
        "deeptutor": {"ok": dt["ok"], "sessions": len(dt["sessions"]),
                      "messages": dt["messages"], "log_events": dt["log_events"],
                      "notes": {k: len(v) for k, v in deeptutor_notes(date).items()}},
        "diary": {"exists": ds["exists"], "mtime": ds["mtime"]},
        "usage": {"apps": n, "total_ms": ms},
    }
