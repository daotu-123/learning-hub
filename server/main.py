# -*- coding: utf-8 -*-
"""
Workbench PC Sync Server (工作台 PC 端同步服务器)
- 局域网内供 Android App 访问
- 聚合: 抖音/小红书当日收藏、DeepTutor 当日活动、Obsidian 日记读写、手机使用时间统计
- 所有数据只在本机 (E:\agent\androd-app\server\data\) 与 Obsidian vault 之间流动, 不上云
"""
import os
import re
import json
import time
import socket
import secrets
import sqlite3
import hashlib
import threading
import datetime
import sys
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import urllib.request
import uvicorn

# ---------------------------------------------------------------- paths
# M1a 配置化：路径/端口/令牌全部来自 config（环境变量驱动，缺省值 = 原硬编码）。
from config import (
    DATA_DIR,
    FAVORITES_ROOT,
    HUB_AUTH_TOKEN,
    HUB_HOST,
    HUB_PORT,
    OBSIDIAN_VAULT,
    PROJECT_ROOT as APP_ROOT,
    USAGE_DB,
)

DATA_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_JSON = DATA_DIR / "settings.json"

DOUYIN_DIR = OBSIDIAN_VAULT / "抖音收藏"
XHS_DIR = FAVORITES_ROOT / "小红书收藏"
DIARY_ROOT = OBSIDIAN_VAULT / "日记"

DEEPTUTOR_DB = Path(r"D:\record\deeptutor\data\user\chat_history.db")
DEEPTUTOR_LOG = Path(r"D:\record\deeptutor\data\user\logs\deeptutor.jsonl")

SERVER_PORT = HUB_PORT

# ---------------------------------------------------------------- helpers
def _utc_to_local(dt_str: str):
    """把带时区的 ISO 时间转成本地 datetime; 失败返回 None"""
    if not dt_str:
        return None
    s = dt_str.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def parse_frontmatter(text: str) -> dict:
    """解析 markdown 前部的 YAML frontmatter"""
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


# ---------------------------------------------------------------- favorites
_cache = {"ts": 0.0, "data": None}
CACHE_TTL = 120.0   # 秒
INDEX_JSON = DATA_DIR / "favorites_index.json"
SCAN_LOCK = threading.Lock()


def _read_head(p: Path, size: int = 2048) -> str:
    """只读文件头(覆盖 frontmatter), 避免全量读大文件"""
    try:
        with open(p, "rb") as fh:
            raw = fh.read(size)
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


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
                text = _read_head(f)
                meta = parse_frontmatter(text)
                dt = _utc_to_local(meta.get("observed_at", ""))
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
                text = _read_head(f)
                meta = parse_frontmatter(text)
                dt = _utc_to_local(meta.get("collected_at", ""))
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


# ---------------------------------------------------------------- deeptutor
def deeptutor_daily(date_str: str) -> dict:
    """读 DeepTutor chat_history.db + 日志, 汇总指定日期的活动"""
    out = {"sessions": [], "messages": 0, "log_events": 0, "ok": False}
    if DEEPTUTOR_DB.exists():
        try:
            con = sqlite3.connect(f"file:{DEEPTUTOR_DB}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            # 当天有消息的会话
            rows = cur.execute(
                """SELECT DISTINCT s.id, s.title, s.created_at,
                          (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id
                            AND date(m.created_at)=?) AS msg_count
                   FROM sessions s
                   WHERE date(s.created_at)=? OR EXISTS(
                       SELECT 1 FROM messages m WHERE m.session_id=s.id AND date(m.created_at)=?)
                   ORDER BY s.updated_at DESC LIMIT 20""",
                (date_str, date_str, date_str),
            ).fetchall()
            for r in rows:
                out["sessions"].append({
                    "id": r["id"], "title": r["title"] or "(无标题)",
                    "created_at": r["created_at"], "msg_count": r["msg_count"],
                })
            out["messages"] = cur.execute(
                "SELECT COUNT(*) FROM messages WHERE date(created_at)=?", (date_str,)
            ).fetchone()[0]
            con.close()
            out["ok"] = True
        except Exception as e:
            out["error"] = str(e)
    if DEEPTUTOR_LOG.exists():
        try:
            cnt = 0
            for line in DEEPTUTOR_LOG.open(encoding="utf-8", errors="ignore"):
                if date_str in line[:80]:
                    cnt += 1
            out["log_events"] = cnt
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- diary
def deeptutor_notes(date_str: str) -> dict:
    """扫描 Obsidian deeptutor/ 下指定日期的新增内容 (与 Obsidian 保持一致)"""
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        return {}
    base = OBSIDIAN_VAULT / "deeptutor"
    out = {"文章": [], "反馈": [], "博主": [], "习题": [], "周记": [], "月记": [], "自我进化": []}
    if not base.exists():
        return {}
    for sub, key in (("每日文章", "文章"), ("每日反馈", "反馈"), ("每日博主", "博主"), ("昨日习题", "习题")):
        p = base / sub / f"{date_str}.md"
        if p.exists():
            out[key].append({"name": sub, "path": str(p), "title": f"{sub} {date_str}"})
    iso = d.isocalendar()
    wk = f"{iso[0]}-W{iso[1]:02d}"
    p = base / "周记" / wk / f"{wk}.md"
    if p.exists():
        out["周记"].append({"name": "周记", "path": str(p), "title": f"周记 {wk}"})
    mo = f"{d.year}-{d.month:02d}"
    p = base / "月记" / mo / f"{mo}.md"
    if p.exists():
        out["月记"].append({"name": "月记", "path": str(p), "title": f"月记 {mo}"})
    ev = base / "自我进化"
    if ev.exists():
        for f in sorted(ev.glob(f"{date_str}-*.md")):
            out["自我进化"].append({"name": "自我进化", "path": str(f), "title": f.stem})
    return {k: v for k, v in out.items() if v}


def _month_dir_name(d: datetime.date) -> str:
    return f"{str(d.year)[2:]}年{d.month}月"


def diary_path(date_str: str) -> Optional[Path]:
    """按 Obsidian 日记目录规则定位文件"""
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        return None
    month_dir = DIARY_ROOT / _month_dir_name(d)
    if not month_dir.exists():
        return None
    cand = month_dir / f"{date_str}.md"
    return cand if cand.exists() else None


def diary_sync_state(date_str: str) -> dict:
    """日记同步状态: 文件 mtime + 内容 hash"""
    p = diary_path(date_str)
    if p is None:
        return {"exists": False, "mtime": 0, "hash": "", "content": ""}
    content = p.read_text(encoding="utf-8", errors="ignore")
    return {
        "exists": True, "mtime": p.stat().st_mtime,
        "hash": hashlib.md5(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


def write_diary(date_str: str, content: str) -> Path:
    """写入/更新 Obsidian 当日日记, 自动建月份目录"""
    d = datetime.date.fromisoformat(date_str)
    month_dir = DIARY_ROOT / _month_dir_name(d)
    month_dir.mkdir(parents=True, exist_ok=True)
    p = month_dir / f"{date_str}.md"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------- health (SQLite)
def _health_conn():
    con = sqlite3.connect(USAGE_DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS health(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, kind TEXT NOT NULL,   -- sleep | exercise
            label TEXT DEFAULT '', value_min INTEGER DEFAULT 0,
            start_ts TEXT DEFAULT '', end_ts TEXT DEFAULT '',
            ts TEXT)"""
    )
    return con


def health_save(date_str, kind, label, value_min, start_ts, end_ts):
    con = _health_conn()
    con.execute(
        "INSERT INTO health(date, kind, label, value_min, start_ts, end_ts, ts) VALUES(?,?,?,?,?,?,?)",
        (date_str, kind, label, value_min, start_ts, end_ts,
         datetime.datetime.now().isoformat(timespec="seconds")))
    con.commit()
    con.close()


def health_daily(date_str):
    con = _health_conn()
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT kind, label, value_min, start_ts, end_ts FROM health WHERE date=? ORDER BY id",
                       (date_str,)).fetchall()
    con.close()
    sleep = [dict(r) for r in rows if r["kind"] == "sleep"]
    exercise = [dict(r) for r in rows if r["kind"] == "exercise"]
    sleep_min = sum(r["value_min"] for r in sleep)
    ex_min = sum(r["value_min"] for r in exercise)
    return {"date": date_str, "sleep": sleep, "exercise": exercise,
            "sleep_min": sleep_min, "exercise_min": ex_min}


def health_trend(days=7):
    con = _health_conn()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT date, kind, SUM(value_min) m FROM health
           WHERE date >= date('now', ?) GROUP BY date, kind""",
        (f"-{days-1} days",)).fetchall()
    con.close()
    out = {}
    for r in rows:
        out.setdefault(r["date"], {})[r["kind"]] = r["m"]
    return out


# ---------------------------------------------------------------- docs (diary / weekly / monthly)
def doc_path(dtype: str, key: str) -> Optional[Path]:
    """定位文档文件. dtype: diary|weekly|monthly; key: 日期/周/月"""
    if dtype == "diary":
        try:
            d = datetime.date.fromisoformat(key)
        except ValueError:
            return None
        return DIARY_ROOT / f"{str(d.year)[2:]}年{d.month}月" / f"{key}.md"
    if dtype == "weekly":
        m = re.match(r"^(\d{4})-W(\d{1,2})$", key)
        if not m:
            return None
        return OBSIDIAN_VAULT / "deeptutor" / "周记" / f"{key}" / f"{key}.md"
    if dtype == "monthly":
        m = re.match(r"^(\d{4})-(\d{1,2})$", key)
        if not m:
            return None
        return OBSIDIAN_VAULT / "deeptutor" / "月记" / f"{key}" / f"{key}.md"
    return None


def doc_read(dtype: str, key: str) -> dict:
    p = doc_path(dtype, key)
    if p is None:
        return {"exists": False, "mtime": 0, "hash": "", "content": "", "path": ""}
    if not p.exists():
        return {"exists": False, "mtime": 0, "hash": "", "content": "", "path": str(p)}
    content = p.read_text(encoding="utf-8", errors="ignore")
    return {
        "exists": True, "mtime": p.stat().st_mtime,
        "hash": hashlib.md5(content.encode("utf-8")).hexdigest(),
        "content": content, "path": str(p),
    }


def doc_write(dtype: str, key: str, content: str) -> Path:
    p = doc_path(dtype, key)
    if p is None:
        raise HTTPException(status_code=400, detail="文档类型或标识不合法")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------- pomodoro (SQLite)
def _pomo_conn():
    con = sqlite3.connect(USAGE_DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS pomodoro(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, task TEXT DEFAULT '',
            minutes INTEGER DEFAULT 25, ts TEXT)"""
    )
    return con


def pomodoro_save(date_str: str, task: str, minutes: int):
    con = _pomo_conn()
    con.execute("INSERT INTO pomodoro(date, task, minutes, ts) VALUES(?,?,?,?)",
                (date_str, task, minutes,
                 datetime.datetime.now().isoformat(timespec="seconds")))
    con.commit()
    con.close()


def pomodoro_daily(date_str: str) -> dict:
    con = _pomo_conn()
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(minutes),0) AS m FROM pomodoro WHERE date=?",
        (date_str,)).fetchone()
    con.close()
    return {"date": date_str, "count": row["c"], "focus_min": row["m"]}


# ---------------------------------------------------------------- usage (SQLite)
def _usage_conn():
    con = sqlite3.connect(USAGE_DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS usage(
            date TEXT, package TEXT, app_name TEXT, total_ms INTEGER, day_ms INTEGER,
            PRIMARY KEY(date, package))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS usage_hourly(
            date TEXT, hour INTEGER, seconds INTEGER,
            PRIMARY KEY(date, hour))"""
    )
    return con


def usage_save(date_str: str, apps: List[dict]):
    con = _usage_conn()
    for a in apps:
        con.execute(
            """INSERT OR REPLACE INTO usage(date, package, app_name, total_ms, day_ms)
               VALUES(?,?,?,?,?)""",
            (date_str, a.get("package", ""), a.get("app_name", ""),
             int(a.get("total_ms", 0)), int(a.get("day_ms", 0))),
        )
    con.commit()
    con.close()


def hourly_save(date_str: str, hours: List[dict]):
    if not hours:
        return
    con = _usage_conn()
    con.execute("DELETE FROM usage_hourly WHERE date=?", (date_str,))
    for h in hours:
        try:
            con.execute("INSERT OR REPLACE INTO usage_hourly(date, hour, seconds) VALUES(?,?,?)",
                        (date_str, int(h.get("hour", 0)), int(h.get("seconds", 0))))
        except Exception:
            pass
    con.commit()
    con.close()


def hourly_daily(date_str: str) -> list:
    con = _usage_conn()
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT hour, seconds FROM usage_hourly WHERE date=? ORDER BY hour",
                       (date_str,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def usage_trend(days: int = 7) -> dict:
    con = _usage_conn()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT date, package, app_name, day_ms FROM usage
           WHERE date >= date('now', ?) ORDER BY date DESC, day_ms DESC""",
        (f"-{days-1} days",),
    ).fetchall()
    con.close()
    dates = sorted({r["date"] for r in rows})
    by_date = {d: [] for d in dates}
    for r in rows:
        by_date[r["date"]].append({
            "package": r["package"], "app_name": r["app_name"], "day_ms": r["day_ms"],
        })
    total_by_date = {d: sum(x["day_ms"] for x in by_date[d]) for d in dates}
    return {"dates": dates, "daily_total_ms": total_by_date, "apps": by_date}


# ---------------------------------------------------------------- settings
def get_settings() -> dict:
    if SETTINGS_JSON.exists():
        try:
            return json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(patch: dict) -> dict:
    s = get_settings()
    s.update(patch)
    SETTINGS_JSON.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return s


# ---------------------------------------------------------------- 访问令牌
# 威胁模型（2026-10-18 审查）：服务绑 0.0.0.0:8637 且 CORS 全开、无鉴权，
# 同网段任意设备可直接读取日记/健康/照片，并可通过 PUT /api/hub/aiconfig
# 覆盖 DeepSeek Key。此外热更新通道 /api/hub/webfile 无鉴权 + 明文 HTTP，
# 改写一份 JS 即可拿到 window.Native 的全部原生能力。
#
# 策略：本机回环请求放行（桌面浏览器体验不变），非回环必须带令牌。
# 令牌来源优先级（M1a 起，既有顺序不变，仅在既有环境变量之后追加 HUB_AUTH_TOKEN）：
#   环境变量 WORKBENCH_AUTH_TOKEN > 环境变量 HUB_AUTH_TOKEN > settings.json > 首次自动生成并落盘。
# 客户端可用 X-Token 头，或用 ?token= 查询参数（<img>/<a> 无法设请求头）。
AUTH_TOKEN_ENV = "WORKBENCH_AUTH_TOKEN"

# 这些路径在任何情况下都不校验令牌：
#  - 静态页面/资源：不校验，否则页面本身都打不开
#  - /api/hub/netinfo：App 首次发现服务器地址时还不知道令牌
#  - /api/auth/token：仅回环可读，桌面端用它把令牌抄到手机上
AUTH_EXEMPT_API = {"/api/hub/netinfo", "/api/auth/token"}


def _loopback(host: str) -> bool:
    """判断请求是否来自本机。"""
    if not host:
        return False
    return host in ("127.0.0.1", "::1", "localhost")


def auth_token() -> str:
    """读取（必要时生成）访问令牌。

    来源顺序（承重项，不许调整）：
      1) 环境变量 WORKBENCH_AUTH_TOKEN（既有）
      2) 环境变量 HUB_AUTH_TOKEN（M1a 新增，与 1 同级，插在既有 env 之后）
      3) settings.json 的 auth_token（既有）
      4) 都没有 → secrets.token_urlsafe(24) 生成并写回 settings.json（既有）
    """
    env = (os.environ.get(AUTH_TOKEN_ENV) or HUB_AUTH_TOKEN or "").strip()
    if env:
        return env
    s = get_settings()
    tok = (s.get("auth_token") or "").strip()
    if not tok:
        tok = secrets.token_urlsafe(24)
        save_settings({"auth_token": tok})
    return tok


def _request_token(request) -> str:
    """从请求里取令牌：优先 X-Token 头，其次 token 查询参数。"""
    h = request.headers.get("x-token") or request.headers.get("X-Token")
    if h:
        return h.strip()
    q = request.query_params.get("token")
    return (q or "").strip()


# ---------------------------------------------------------------- API models
class UsageReport(BaseModel):
    date: str
    apps: List[dict] = []
    hourly: List[dict] = []   # [{hour, seconds}] 今日按小时活跃分布


class DiaryUpdate(BaseModel):
    date: str
    content: str
    base_updated_at: float = 0.0   # 客户端上次拉取时的服务器 mtime
    client_updated_at: float = 0.0  # 客户端本地最后修改时间


class SettingsPatch(BaseModel):
    background: Optional[str] = None
    accent: Optional[str] = None
    theme: Optional[str] = None


class PomoReport(BaseModel):
    date: str
    task: str = ""
    minutes: int = 25


# ---------------------------------------------------------------- app
app = FastAPI(title="Workbench Sync Server", version="1.1.0")
# allow_private_network=True：APK 页面源是 http://appassets.androidplatform.net
# （私有网络地址），访问 LAN 的 http://192.168.x.x:8637 时 Chrome 会发
# Access-Control-Request-Private-Network 预检。Starlette 的 CORSMiddleware 默认
# 拒绝该预检（400 Disallowed CORS private-network），必须在此显式放行。
app.add_middleware(
    CORSMiddleware,
    # 2026-10-18 收紧：原来是 allow_origins=["*"]，配合「无鉴权 + 绑 0.0.0.0」
    # 等于把日记/健康/照片和 AI Key 完全暴露给同网段。现改为白名单：
    #   - APK 页面源 appassets.androidplatform.net
    #   - 本机、局域网私有网段、Tailscale 的 100.64.0.0/10
    # 真正的访问控制靠 X-Token 鉴权中间件，CORS 只是收敛面。
    allow_origins=[
        "http://appassets.androidplatform.net",
        "https://appassets.androidplatform.net",
    ],
    allow_origin_regex=(
        r"^https?://("
        r"localhost|127\.0\.0\.1|\[::1\]|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
        r"100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
        r")(?::\d+)?$"
    ),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)

@app.middleware("http")
async def allow_private_network(request, call_next):
    """兜底：给带 PNA 预检标记的响应补上 allow-private-network（老版本 Starlette 兼容）。"""
    resp = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


@app.get("/api/auth/token")
def auth_token_endpoint(request: Request):
    """把令牌交给本机（仅回环）。桌面浏览器用它显示，供手机端录入。"""
    host = request.client.host if request.client else ""
    if not _loopback(host):
        raise HTTPException(status_code=403, detail="仅本机可读取令牌")
    return {"token": auth_token()}


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """非回环访问 /api/* 必须带令牌。

    放行规则：
      1) 非 /api/ 路径（静态页面与资源）——不校验，否则页面本身打不开
      2) AUTH_EXEMPT_API 白名单（netinfo 供首次发现服务器；auth/token 仅回环可读）
      3) 本机回环请求——桌面浏览器体验不变
    其余一律要求 X-Token 头或 ?token= 参数。
    """
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    if path in AUTH_EXEMPT_API:
        return await call_next(request)
    host = request.client.host if request.client else ""
    if _loopback(host):
        return await call_next(request)
    expected = auth_token()
    given = _request_token(request)
    if expected and given and secrets.compare_digest(given, expected):
        return await call_next(request)
    return JSONResponse(
        {"error": "unauthorized", "hint": "非本机访问需带 X-Token 请求头（或在设置页录入令牌）"},
        status_code=401,
    )

# Learning Hub 只读中枢（/api/hub/* + /hub 页面）
from hub.router import router as hub_router, find_tailscale_ip
app.include_router(hub_router)

# 健康检查（/health/live、/health/ready）——在 /api/ 之外，不进鉴权中间件
from health import router as health_router
app.include_router(health_router)

# Learning Hub: OpenMAIC AI 课堂（/api/hub/openmaic/*）
from hub.openmaic import router as openmaic_router
app.include_router(openmaic_router)

HUB_WEB = APP_ROOT / "server" / "hub_web"
if not HUB_WEB.exists() and getattr(sys, "frozen", False):
    # PyInstaller 打包运行时：磁盘路径缺失时回退到包内资源（hub_web 随 --add-data 打入）
    HUB_WEB = Path(sys._MEIPASS) / "hub_web"


@app.get("/hub")
def hub_page():
    """学习中枢入口页"""
    p = HUB_WEB / "hub.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="hub.html 未构建")
    return FileResponse(str(p))


@app.get("/server.js")
def server_js():
    """公共服务器模块（学习中枢页引用）"""
    p = HUB_WEB / "server.js"
    if not p.exists():
        raise HTTPException(status_code=404, detail="server.js 未部署")
    return FileResponse(str(p), media_type="application/javascript")


@app.get("/hub/{path:path}")
def hub_assets(path: str):
    """学习中枢静态资源（css/js）"""
    if ".." in path or "\\" in path or ":" in path:
        raise HTTPException(status_code=400, detail="非法路径")
    p = HUB_WEB / path
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(str(p))


# ------------------------------------------------ 新版单 App（Vue SPA，web/ 构建产物）
# 三 Tab 合一：学习中枢 / 题库 / 工作台，hash 路由，同时供 Web 与 APK(file://) 使用
APP_DIST = APP_ROOT / "server" / "web_dist" / "app"
if not APP_DIST.exists() and getattr(sys, "frozen", False):
    APP_DIST = Path(sys._MEIPASS) / "web_dist" / "app"


@app.get("/app")
def app_index():
    """新版单 App 入口（SPA index.html）"""
    p = APP_DIST / "index.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="SPA 未构建：请先在 web/ 目录执行 npm run build")
    return FileResponse(str(p))


@app.get("/app/{path:path}")
def app_assets(path: str):
    """SPA 静态资源（hash 路由，无需服务端回退）"""
    if not path:
        path = "index.html"          # /app/ 与 /app 都落到入口
    if ".." in path or "\\" in path or ":" in path:
        raise HTTPException(status_code=400, detail="非法路径")
    p = APP_DIST / path
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if path.endswith(".js"):
        media = "text/javascript"
    elif path.endswith(".css"):
        media = "text/css"
    elif path.endswith(".html"):
        media = "text/html"
    elif path.endswith(".json"):
        media = "application/json"
    else:
        media = None
    return FileResponse(str(p), media_type=media)


LAN_IP = None


# ---------------------------------------------------------------- tasks (Obsidian Tasks plugin format)
TASKS_DIR = OBSIDIAN_VAULT / "TaskNotes" / "Tasks"


def _parse_task_file(p: Path) -> dict:
    text = p.read_text(encoding="utf-8", errors="ignore")
    meta = parse_frontmatter(text)
    return {
        "file": p.name,
        "name": p.stem,
        "status": meta.get("status", "open"),
        "priority": meta.get("priority", "normal"),
        "scheduled": meta.get("scheduled", ""),
        "due": meta.get("due", ""),
        "mtime": p.stat().st_mtime,
    }


def _touch_modified(text: str) -> str:
    """更新 frontmatter dateModified 字段"""
    now = datetime.datetime.now().isoformat(timespec="milliseconds") + "+08:00"
    if re.search(r"^dateModified:.*$", text, flags=re.M):
        return re.sub(r"^dateModified:.*$", f"dateModified: {now}", text, count=1, flags=re.M)
    return text


@app.get("/api/tasks")
def tasks_get():
    if not TASKS_DIR.exists():
        return {"tasks": [], "server_ts": 0}
    tasks = []
    for p in sorted(TASKS_DIR.glob("*.md")):
        try:
            tasks.append(_parse_task_file(p))
        except Exception:
            continue
    server_ts = max([t["mtime"] for t in tasks], default=0.0)
    return {"tasks": tasks, "server_ts": server_ts}


class TaskAdd(BaseModel):
    name: str


class TaskPatch(BaseModel):
    file: str
    action: str                  # toggle | delete | timeEntry
    done: Optional[bool] = None
    base_mtime: float = 0.0
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None


@app.post("/api/tasks/add")
def task_add(a: TaskAdd):
    name = a.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="任务名为空")
    safe = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    if not safe:
        raise HTTPException(status_code=400, detail="任务名不合法")
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    p = TASKS_DIR / (safe + ".md")
    if p.exists():
        raise HTTPException(status_code=409, detail="任务已存在")
    now = datetime.datetime.now()
    content = (
        "---\n"
        f"status: open\n"
        "priority: normal\n"
        f"scheduled: {now.date().isoformat()}\n"
        f"dateCreated: {now.isoformat(timespec='milliseconds')}+08:00\n"
        f"dateModified: {now.isoformat(timespec='milliseconds')}+08:00\n"
        "tags:\n"
        "  - task\n"
        "---\n\n"
    )
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "task": _parse_task_file(p)}


@app.post("/api/tasks/patch")
def task_patch(upd: TaskPatch):
    if not upd.file or "/" in upd.file or "\\" in upd.file:
        raise HTTPException(status_code=400, detail="非法文件名")
    p = TASKS_DIR / upd.file
    if not p.exists():
        raise HTTPException(status_code=404, detail="任务不存在")
    cur = p.stat().st_mtime
    if upd.base_mtime > 0 and cur > upd.base_mtime + 1:
        raise HTTPException(status_code=409, detail={
            "message": "任务在 PC 端已被修改",
            "task": _parse_task_file(p),
        })
    if upd.action == "delete":
        p.unlink()
        return {"ok": True, "deleted": upd.file}
    text = p.read_text(encoding="utf-8", errors="ignore")
    if upd.action == "toggle" and upd.done is not None:
        new_status = "done" if upd.done else "open"
        if re.search(r"^status:.*$", text, flags=re.M):
            text = re.sub(r"^status:.*$", f"status: {new_status}", text, count=1, flags=re.M)
        text = _touch_modified(text)
    elif upd.action == "timeEntry" and upd.start_ts and upd.end_ts:
        entry = (f"  - startTime: {upd.start_ts}\n"
                 f"    description: Work session\n"
                 f"    endTime: {upd.end_ts}")
        if "timeEntries:" in text:
            text = text.rstrip() + "\n" + entry + "\n"
        else:
            text = text.rstrip() + "\n\ntimeEntries:\n" + entry + "\n"
        text = _touch_modified(text)
    else:
        raise HTTPException(status_code=400, detail="未知操作")
    p.write_text(text, encoding="utf-8")
    return {"ok": True, "task": _parse_task_file(p)}


# ---------------------------------------------------------------- health / docs API
class HealthReport(BaseModel):
    date: str
    kind: str            # sleep | exercise
    label: str = ""
    value_min: int = 0
    start_ts: str = ""
    end_ts: str = ""


class DocUpdate(BaseModel):
    dtype: str           # diary | weekly | monthly
    key: str
    content: str
    base_updated_at: float = 0.0


@app.post("/api/health")
def health_post(r: HealthReport):
    if r.kind not in ("sleep", "exercise"):
        raise HTTPException(status_code=400, detail="kind 必须是 sleep 或 exercise")
    health_save(r.date, r.kind, r.label, r.value_min, r.start_ts, r.end_ts)
    return {"ok": True, "date": r.date, "kind": r.kind}


@app.get("/api/health")
def health_get(date: str = Query(default_factory=lambda: datetime.date.today().isoformat()),
               days: int = 0):
    if days > 0:
        return health_trend(days)
    return health_daily(date)


class DailyReport(BaseModel):
    date: str
    content: str


@app.post("/api/daily-report")
def daily_report_post(r: DailyReport):
    """把手机端组装的日报写入 Obsidian (工作台日报/{date}.md)"""
    try:
        d = datetime.date.fromisoformat(r.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")
    p = OBSIDIAN_VAULT / "工作台日报" / f"{d.isoformat()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(r.content, encoding="utf-8")
    return {"ok": True, "path": str(p), "mtime": p.stat().st_mtime}


@app.get("/api/daily-report")
def daily_report_get(date: str):
    try:
        d = datetime.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")
    p = OBSIDIAN_VAULT / "工作台日报" / f"{d.isoformat()}.md"
    if not p.exists():
        return {"exists": False, "date": date}
    return {"exists": True, "date": date, "path": str(p)}


@app.get("/api/doc")
def doc_get(dtype: str, key: str):
    return doc_read(dtype, key)


@app.put("/api/doc")
def doc_put(upd: DocUpdate):
    cur = doc_read(upd.dtype, upd.key)
    if cur["exists"] and upd.base_updated_at > 0 and cur["mtime"] > upd.base_updated_at + 1:
        raise HTTPException(status_code=409, detail={
            "message": "PC 端文档已被修改, 存在冲突",
            "server": cur,
        })
    p = doc_write(upd.dtype, upd.key, upd.content)
    return {"ok": True, "path": str(p), "mtime": p.stat().st_mtime}


@app.on_event("startup")
def _startup():
    """冷启动: 加载持久化索引 + 启动后台刷新线程"""
    load_index_on_start()
    t = threading.Thread(target=background_refresh, daemon=True)
    t.start()


@app.get("/")
def root():
    return {
        "app": "workbench-sync-server", "version": "1.0.0",
        "now": datetime.datetime.now().isoformat(timespec="seconds"),
        "lan_ip": LAN_IP, "port": SERVER_PORT,
        "tailscale_ip": find_tailscale_ip(),
    }


@app.get("/api/summary")
def summary(date: str = Query(default_factory=lambda: datetime.date.today().isoformat())):
    favs = scan_favorites()
    day_favs = favs.get(date, {})
    dt = deeptutor_daily(date)
    ds = diary_sync_state(date)
    con = _usage_conn()
    con.row_factory = sqlite3.Row
    usage_rows = con.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(day_ms),0) AS ms FROM usage WHERE date=?", (date,)
    ).fetchone()
    con.close()
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
        "usage": {"apps": usage_rows["n"], "total_ms": usage_rows["ms"]},
    }


@app.get("/api/deeptutor/notes")
def deeptutor_notes_api(date: str = Query(default_factory=lambda: datetime.date.today().isoformat())):
    return deeptutor_notes(date)


@app.get("/api/favorites")
def favorites(date: str = Query(default_factory=lambda: datetime.date.today().isoformat()),
              platform: Optional[str] = None):
    favs = scan_favorites()
    day_favs = favs.get(date, {})
    if platform:
        return {"date": date, "platform": platform, "items": day_favs.get(platform, [])}
    return {"date": date, "douyin": day_favs.get("douyin", []),
            "xiaohongshu": day_favs.get("xiaohongshu", [])}


@app.get("/api/deeptutor")
def deeptutor(date: str = Query(default_factory=lambda: datetime.date.today().isoformat())):
    return deeptutor_daily(date)


@app.get("/api/usage")
def usage(days: int = 7):
    return usage_trend(days)


@app.post("/api/usage")
def usage_post(report: UsageReport):
    usage_save(report.date, report.apps)
    hourly_save(report.date, report.hourly)
    return {"ok": True, "date": report.date, "apps": len(report.apps)}


@app.post("/api/pomodoro")
def pomodoro_post(report: PomoReport):
    pomodoro_save(report.date, report.task, report.minutes)
    return {"ok": True, "date": report.date}


@app.get("/api/pomodoro")
def pomodoro_get(date: str = Query(default_factory=lambda: datetime.date.today().isoformat())):
    return pomodoro_daily(date)


@app.get("/api/diary")
def diary_get(date: str = Query(default_factory=lambda: datetime.date.today().isoformat())):
    return diary_sync_state(date)


@app.put("/api/diary")
def diary_put(upd: DiaryUpdate):
    cur = diary_sync_state(upd.date)
    if cur["exists"] and upd.base_updated_at > 0 and cur["mtime"] > upd.base_updated_at + 1:
        raise HTTPException(status_code=409, detail={
            "message": "PC 端日记已被修改, 存在冲突",
            "server": cur,
        })
    p = write_diary(upd.date, upd.content)
    return {"ok": True, "path": str(p), "mtime": p.stat().st_mtime}


@app.get("/api/settings")
def settings_get():
    return get_settings()


@app.put("/api/settings")
def settings_put(patch: SettingsPatch):
    return save_settings(patch.dict(exclude_none=True))


IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")


@app.get("/img/{path:path}")
def vault_image(path: str):
    """通用 vault 图片服务: 日记里的 ![[路径]] 图片都能在手机上查看/下载"""
    if ".." in path or ":" in path or "\\" in path:
        raise HTTPException(status_code=400, detail="非法路径")
    p = OBSIDIAN_VAULT / path
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if p.suffix.lower() not in IMG_EXTS:
        raise HTTPException(status_code=400, detail="非图片文件")
    return FileResponse(str(p))


# ---------------------------------------------------------------- 照片同步
PHOTO_ROOT = OBSIDIAN_VAULT / "工作台照片"


class PhotoUpload(BaseModel):
    date: str
    name: str = "photo.jpg"
    data: str = ""   # base64 (可含 data:image/jpeg;base64, 前缀)


def _photo_path(date_str: str, name: str) -> Path:
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        d = datetime.date.today()
    month_dir = PHOTO_ROOT / f"{d.year}-{d.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    # 安全文件名: 时间戳 + 原扩展名
    ext = os.path.splitext(name)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        ext = ".jpg"
    fname = f"{datetime.datetime.now().strftime('%H%M%S')}_{d.isoformat()}{ext}"
    return month_dir / fname


@app.post("/api/photo/upload")
def photo_upload(r: PhotoUpload):
    import base64 as b64
    if not r.data:
        raise HTTPException(status_code=400, detail="无图片数据")
    payload = r.data
    if "," in payload and payload.startswith("data:"):
        payload = payload.split(",", 1)[1]
    try:
        raw = b64.b64decode(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="base64 解码失败")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="图片超过 20MB")
    p = _photo_path(r.date, r.name)
    p.write_bytes(raw)
    rel = str(p.relative_to(OBSIDIAN_VAULT)).replace("\\", "/")
    parts = rel.split("/")   # 工作台照片/月份/文件
    return {"ok": True, "path": str(p), "rel": rel,
            "url": "/photos/" + "/".join(parts[1:])}


@app.get("/api/photos")
def photos_list(month: str = "", limit: int = 200):
    """列出工作台照片, 按月份过滤, 最新的在前"""
    if not PHOTO_ROOT.exists():
        return {"photos": [], "months": []}
    months = sorted([d.name for d in PHOTO_ROOT.iterdir() if d.is_dir()], reverse=True)
    if month and month not in months:
        return {"photos": [], "months": months}
    targets = [PHOTO_ROOT / month] if month else [PHOTO_ROOT / m for m in months]
    photos = []
    for t in targets:
        if not t.exists():
            continue
        for f in sorted(t.iterdir(), reverse=True):
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                rel = str(f.relative_to(OBSIDIAN_VAULT)).replace("\\", "/")
                parts = rel.split("/")
                photos.append({
                    "path": rel,
                    "url": "/photos/" + "/".join(parts[1:]),
                    "month": parts[1],
                    "name": f.name,
                    "size": f.stat().st_size,
                })
    photos.sort(key=lambda p: p["path"], reverse=True)
    return {"photos": photos[:limit], "months": months}


@app.get("/photos/{month}/{name}")
def photo_file(month: str, name: str):
    if "/" in name or "\\" in name or ".." in name or "/" in month or ".." in month:
        raise HTTPException(status_code=400, detail="非法路径")
    p = PHOTO_ROOT / month / name
    if not p.exists():
        raise HTTPException(status_code=404, detail="照片不存在")
    return FileResponse(str(p))


# ---------------------------------------------------------------- AI 助手 (WorkBuddy 风格对话)
AI_ENV = Path(r"C:\Users\Administrator\AppData\Local\hermes\.env")
HOMEWORK_WEAK = Path(r"E:\obsidian\depot\homework\AI错题本\薄弱点分析.md")


def _ai_key():
    # 优先读 settings.json 里通过 /api/hub/aiconfig 配置的 Key
    try:
        s = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        k = (s.get("ai") or {}).get("deepseek_key", "")
        if k:
            return k
    except Exception:
        pass
    try:
        for line in AI_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _build_context(date_str: str) -> str:
    """组装工作台今日数据摘要, 供 AI 理解用户状态"""
    parts = []
    try:
        favs = scan_favorites()
        day = favs.get(date_str, {})
        dt = deeptutor_daily(date_str)
        notes = deeptutor_notes(date_str)
        ds = diary_sync_state(date_str)
        con = _usage_conn()
        con.row_factory = sqlite3.Row
        u = con.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(day_ms),0) AS ms FROM usage WHERE date=?",
            (date_str,)).fetchone()
        con.close()
        note_sum = "、".join(f"{k}{len(v)}" for k, v in notes.items()) if notes else "无"
        parts.append(
            f"今日({date_str})概览: 收藏 抖音{len(day.get('douyin', []))}条/小红书{len(day.get('xiaohongshu', []))}条; "
            f"DeepTutor 会话{len(dt['sessions'])}个/消息{dt['messages']}条, Obsidian新增内容[{note_sum}]; "
            f"日记{'已写' if ds['exists'] else '未写'}; 使用统计 应用{u['n']}个/总时长{round(u['ms']/60000)}分钟")
        for k, items in notes.items():
            for it in items[:2]:
                try:
                    txt = Path(it["path"]).read_text(encoding="utf-8", errors="ignore")[:300]
                    parts.append(f"[{k}] {it['title']}:\n{txt}")
                except Exception:
                    pass
    except Exception as e:
        parts.append(f"(概览读取失败: {e})")
    try:
        t = usage_trend(7)
        parts.append("近7天使用时长(分钟): " + json.dumps(
            {k: round(v / 60000) for k, v in t.items()}, ensure_ascii=False))
    except Exception:
        pass
    try:
        p = pomodoro_daily(date_str)
        parts.append(f"今日番茄钟: {p['count']}个/专注{p['focus_min']}分钟")
    except Exception:
        pass
    try:
        # 昨日数据 (复盘用)
        y_date = (datetime.date.fromisoformat(date_str) - datetime.timedelta(days=1)).isoformat()
        y_p = pomodoro_daily(y_date)
        y_h = health_daily(y_date)
        y_d = doc_read("diary", y_date)
        y_parts = [f"昨日({y_date})番茄{p['count']}个/专注{p['focus_min']}分钟"]
        y_parts.append(f"睡眠{y_h['sleep_min']}分钟/运动{y_h['exercise_min']}分钟")
        if y_d["exists"]:
            y_parts.append("日记:" + y_d["content"][:200])
        parts.append("; ".join(y_parts))
    except Exception:
        pass
    try:
        # 近7天汇总 (周总结用)
        wk = {}
        for i in range(7):
            d = (datetime.date.fromisoformat(date_str) - datetime.timedelta(days=i)).isoformat()
            p = pomodoro_daily(d)
            wk[d] = {"pomo": p["count"], "focus": p["focus_min"]}
        parts.append("近7天番茄钟: " + json.dumps(wk, ensure_ascii=False))
        ht = health_trend(7)
        parts.append("近7天健康(分钟): " + json.dumps(ht, ensure_ascii=False))
    except Exception:
        pass
    try:
        # 今日小时活跃度 (高效时段分析用)
        hrs = hourly_daily(date_str)
        if hrs:
            peak = max(hrs, key=lambda h: h["seconds"])
            active = [h for h in hrs if h["seconds"] > 0]
            parts.append(f"今日活跃时段: 高峰{peak['hour']}:00-{peak['hour']+1}:00({round(peak['seconds']/60)}分钟), 共{len(active)}个活跃小时: " +
                         ", ".join(f"{h['hour']}:00({round(h['seconds']/60)}m)" for h in active[:12]))
    except Exception:
        pass
    try:
        h = health_daily(date_str)
        parts.append(f"今日健康: 睡眠{h['sleep_min']}分钟/运动{h['exercise_min']}分钟")
    except Exception:
        pass
    try:
        tasks = []
        if TASKS_DIR.exists():
            for p in sorted(TASKS_DIR.glob("*.md")):
                try:
                    t = _parse_task_file(p)
                    tasks.append(f"{t['name']}({'已完成' if t['status'] == 'done' else '进行中'})")
                except Exception:
                    pass
        parts.append("任务清单: " + ("; ".join(tasks[:20]) if tasks else "无"))
    except Exception:
        pass
    try:
        d = doc_read("diary", date_str)
        if d["exists"]:
            parts.append("今日日记内容:\n" + d["content"][:800])
    except Exception:
        pass
    try:
        if HOMEWORK_WEAK.exists():
            txt = HOMEWORK_WEAK.read_text(encoding="utf-8")
            m = re.search(r"## 薄弱考点 Top.*?(?=## |\Z)", txt, re.S)
            if m:
                parts.append("考研薄弱考点:\n" + m.group(0)[:600])
    except Exception:
        pass
    return "\n".join(parts)


class AIChat(BaseModel):
    messages: List[dict] = []
    date: str = ""


@app.post("/api/ai/chat")
def ai_chat(r: AIChat):
    key = _ai_key()
    if not key:
        raise HTTPException(status_code=503, detail="PC 端未配置 DeepSeek API Key")
    date = r.date or datetime.date.today().isoformat()
    ctx = _build_context(date)
    sys_prompt = (
        "你是用户手机工作台的 AI 助手(类似腾讯 WorkBuddy 的数字同事)。"
        "基于下面的用户工作台数据回答问题：做总结、分析趋势、指出问题、给建议、制定学习/生活计划。"
        "数据来自手机+PC 同步，可能不完整，请如实说明。"
        "回答用简洁口语化中文，多用短段落和要点列表，不要客套。\n\n"
        "=== 用户工作台数据 ===" + ctx
    )
    msgs = [{"role": "system", "content": sys_prompt}]
    for m in r.messages[-10:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": str(m["content"])[:2000]})
    if len(msgs) == 1:
        msgs.append({"role": "user", "content": "你好，介绍一下我今天的整体情况"})
    payload = {
        "model": "deepseek-chat",
        "messages": msgs,
        "temperature": 0.5,
        "max_tokens": 1200,
    }
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        resp = json.loads(urllib.request.urlopen(req, timeout=90).read().decode("utf-8"))
        return {"reply": resp["choices"][0]["message"]["content"]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {e}")


@app.get("/api/ai/context")
def ai_context(date: str = Query(default_factory=lambda: datetime.date.today().isoformat())):
    return {"date": date, "context": _build_context(date)}


# ---------------------------------------------------------------- main
def find_lan_ip() -> Optional[str]:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def start_udp_broadcast(port: int, name: str) -> None:
    """局域网 UDP 广播服务存在性（手机 App 自动发现），协议: LEARNINGHUB|<name>|<port>"""
    import socket
    import threading

    def loop():
        msg = ("LEARNINGHUB|%s|%d" % (name, port)).encode("utf-8")
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(msg, ("255.255.255.255", 8638))
                s.close()
            except Exception:
                pass
            time.sleep(2)

    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    LAN_IP = find_lan_ip()
    # UDP 广播：手机 App 自动发现（学习中枢 8637）
    import platform
    start_udp_broadcast(SERVER_PORT, platform.node() or "PC")
    # 文件日志 (后台静默启动时无控制台, 排障依赖 server.log)
    LOG_FILE = DATA_DIR / "server.log"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"f": {"format": "%(asctime)s %(levelname)s %(message)s"}},
        "handlers": {
            "h": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(LOG_FILE),
                "maxBytes": 2 * 1024 * 1024,
                "backupCount": 2,
                "encoding": "utf-8",
                "formatter": "f",
            }
        },
        "root": {"level": "INFO", "handlers": ["h"]},
    }
    print("=" * 56)
    print("  工作台同步服务器 v1.0.0")
    print(f"  本机 IP: {LAN_IP}   端口: {SERVER_PORT}")
    ts_ip = find_tailscale_ip()
    if ts_ip:
        print(f"  Tailscale 远程地址: http://{ts_ip}:{SERVER_PORT}  (手机不连同一 WiFi 也能同步)")
    else:
        print("  Tailscale: 未检测到 (安装并登录后自动支持跨网络同步)")
    print(f"  数据目录: {DATA_DIR}")
    print(f"  日志文件: {LOG_FILE}")
    print(f"  手机 App 设置服务器地址为: http://<本机IP>:{SERVER_PORT}")
    print("=" * 56)

    # 端口已被占用（服务已在运行）→ 只打开网页，不重复启动（与 start_hub.bat 行为一致）
    def _port_busy(port: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            return False
        except OSError:
            return True
        finally:
            s.close()

    if _port_busy(SERVER_PORT):
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{SERVER_PORT}/hub")
        print("  服务已在运行，已为你打开网页。")
        sys.exit(0)

    # 后台线程：服务就绪后自动打开浏览器（打包为无窗口 exe 时这是唯一可见反馈）
    def _open_browser():
        import urllib.request
        import webbrowser
        for _ in range(40):
            time.sleep(0.5)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{SERVER_PORT}/", timeout=1)
                break
            except Exception:
                pass
        try:
            webbrowser.open(f"http://127.0.0.1:{SERVER_PORT}/hub")
        except Exception:
            pass

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host=HUB_HOST, port=SERVER_PORT, log_level="info", log_config=LOG_CONFIG)
