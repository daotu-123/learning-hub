# -*- coding: utf-8 -*-
"""
Learning Hub: router
FastAPI 路由：/api/hub/*
学习数据中枢 —— 读取 Obsidian vault 与 F 盘账本；设置/壁纸/番茄钟/任务勾选/
复习完成/自建计划可写（写入统一走 hub.writer，均先备份再原子替换）。
"""
import base64
import datetime
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import vault_reader as vr
from . import queue_reader as qr
from . import writer as wr

router = APIRouter(prefix="/api/hub", tags=["hub"])

# M1a：data 目录改由 config 单一来源（原为本文件硬编码），
# 否则 HUB_DATA_DIR 环境变量只会改变 main.py 的落点而这里不跟着变。
import config
from config import DATA_DIR

SETTINGS_JSON = DATA_DIR / "settings.json"
WALLPAPER_DIR = DATA_DIR / "wallpapers"
WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
USAGE_DB = config.USAGE_DB   # 工作台 SQLite（pomodoro 表）

# 网页热更新源（单 App：web_dist/app 与 APK assets/www 同构；VERSION 为整数版本号）
WEB_ROOT = Path(r"E:\agent\androd-app\server\web_dist")
if not WEB_ROOT.exists() and getattr(sys, "frozen", False):
    # PyInstaller 打包运行时：磁盘路径缺失时回退到包内资源（web_dist 随 --add-data 打入）
    WEB_ROOT = Path(sys._MEIPASS) / "web_dist"
WEB_DIST = WEB_ROOT / "app"          # 页面根：热更新按此目录列文件、读内容
WEB_VERSION_FILE = WEB_ROOT / "VERSION"   # 版本号留在 app/ 之外（vite 会清空 outDir）

# 内置氛围渐变壁纸（CSS background 值，无需文件）
BUILTIN_WALLPAPERS = {
    "none": "无壁纸（纯深色底）",
    "rain": "雨林暮色（墨绿光晕）",
    "snow": "雪夜静谧（淡蓝光晕）",
    "cloud": "暖云薄暮（暗灰暖光）",
    "forest": "林间透光（翠绿光柱）",
    "aurora": "极光夜（青紫光带）",
    "dusk": "落日余晖（橙红渐暗）",
}

DEFAULT_HUB_SETTINGS = {
    "wallpaper": "rain",      # 内置 key 或 "/api/hub/wallpapers/xxx.jpg"
    "accent": "#d7ef83",      # 强调色
    "glass": 55,              # 玻璃卡片不透明度 30-85
    "slogan": "",             # 空 = 用场景默认标语
    "scene": "rain",          # 雨林/雪日/暖云（背景明暗基调）
}


def _get_settings() -> dict:
    if SETTINGS_JSON.exists():
        try:
            return json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_settings(patch: dict) -> dict:
    s = _get_settings()
    s.update(patch)
    SETTINGS_JSON.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return s


def _hub_settings() -> dict:
    s = _get_settings().get("hub", {})
    merged = dict(DEFAULT_HUB_SETTINGS)
    merged.update({k: v for k, v in s.items() if v is not None and v != ""})
    return merged


class HubSettingsPatch(BaseModel):
    wallpaper: Optional[str] = None
    accent: Optional[str] = None
    glass: Optional[int] = None
    slogan: Optional[str] = None
    scene: Optional[str] = None


class WallpaperUpload(BaseModel):
    data: str = ""     # base64 (可含 data:image/xxx;base64, 前缀)


@router.get("/settings")
def hub_settings_get():
    """学习中枢自定义设置（含内置壁纸清单）"""
    s = _hub_settings()
    s["builtins"] = BUILTIN_WALLPAPERS
    return s


@router.put("/settings")
def hub_settings_put(patch: HubSettingsPatch):
    """保存学习中枢自定义设置"""
    p = patch.dict(exclude_none=True)
    # 校验
    if "accent" in p and not re.match(r"^#[0-9a-fA-F]{6}$", p["accent"]):
        raise HTTPException(status_code=400, detail="accent 必须是 #RRGGBB")
    if "glass" in p and not (20 <= p["glass"] <= 90):
        raise HTTPException(status_code=400, detail="glass 范围 20-90")
    if "scene" in p and p["scene"] not in ("rain", "snow", "cloud"):
        raise HTTPException(status_code=400, detail="scene 必须是 rain/snow/cloud")
    s = _get_settings()
    hub = dict(s.get("hub", {}))
    hub.update(p)
    s["hub"] = hub
    _save_settings({"hub": hub})
    return _hub_settings()


@router.post("/wallpaper")
def hub_wallpaper_upload(up: WallpaperUpload):
    """上传自定义壁纸（base64 → wallpapers/xxx.jpg），返回可访问 URL"""
    data = up.data or ""
    if "," in data and data.startswith("data:"):
        head, _, b64 = data.partition(",")
        m = re.search(r"image/(\w+)", head)
        ext = m.group(1) if m else "jpg"
        if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
            ext = "jpg"
    else:
        b64 = data
        ext = "jpg"
    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=400, detail="base64 解码失败")
    if not raw or len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片为空或超过 15MB")
    name = f"custom-{datetime.date.today().isoformat()}-{uuid.uuid4().hex[:8]}.{ext}"
    (WALLPAPER_DIR / name).write_bytes(raw)
    url = f"/api/hub/wallpapers/{name}"
    # 同时更新设置为该壁纸
    s = _get_settings()
    hub = dict(s.get("hub", {}))
    hub["wallpaper"] = url
    s["hub"] = hub
    _save_settings({"hub": hub})
    return {"url": url, "settings": _hub_settings()}


@router.get("/wallpapers/{name}")
def hub_wallpaper_get(name: str):
    """壁纸图片静态服务"""
    if ".." in name or "\\" in name or "/" in name or ":" in name:
        raise HTTPException(status_code=400, detail="非法路径")
    p = WALLPAPER_DIR / name
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="壁纸不存在")
    return FileResponse(str(p))


# ---------------------------------------------------------------- 番茄钟（复用工作台 pomodoro 表）
def _pomo_daily(date_str: str) -> dict:
    con = sqlite3.connect(USAGE_DB)
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS pomodoro(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL, task TEXT DEFAULT '',
                minutes INTEGER DEFAULT 25, ts TEXT)"""
        )
        row = con.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(minutes),0) AS m FROM pomodoro WHERE date=?",
            (date_str,)).fetchone()
    finally:
        con.close()
    return {"date": date_str, "count": row[0], "focus_min": row[1]}


@router.get("/focus")
def hub_focus(days: int = Query(7, ge=1, le=30)):
    """近 N 天番茄钟趋势（读工作台 pomodoro 表）"""
    today = datetime.date.today()
    out = []
    total_count = total_min = 0
    for i in range(days):
        d = today - datetime.timedelta(days=days - 1 - i)
        day = _pomo_daily(d.isoformat())
        total_count += day["count"]
        total_min += day["focus_min"]
        out.append(day)
    return {"days": days, "data": out, "total_count": total_count, "total_min": total_min}


class PomoReportIn(BaseModel):
    date: Optional[str] = None
    task: str = ""
    minutes: int = 25


@router.post("/focus")
def hub_focus_save(r: PomoReportIn):
    """记录一个完成的番茄钟（写工作台 pomodoro 表，手机同步可见）"""
    date_str = r.date or datetime.date.today().isoformat()
    if not (1 <= r.minutes <= 180):
        raise HTTPException(status_code=400, detail="minutes 范围 1-180")
    con = sqlite3.connect(USAGE_DB)
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS pomodoro(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL, task TEXT DEFAULT '',
                minutes INTEGER DEFAULT 25, ts TEXT)"""
        )
        con.execute(
            "INSERT INTO pomodoro(date, task, minutes, ts) VALUES(?,?,?,?)",
            (date_str, r.task[:120], r.minutes,
             datetime.datetime.now().isoformat(timespec="seconds")))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "date": date_str, "saved": _pomo_daily(date_str)}


def _today() -> str:
    return datetime.date.today().isoformat()


@router.get("/overview")
def hub_overview(days: int = Query(30, ge=1, le=120)):
    """打卡热力图 + 积分趋势（最近 N 天）"""
    return vr.overview(days)


@router.get("/today")
def hub_today(date: str = Query(default_factory=_today)):
    """今日视图：日记摘要 + 复习到期 + 反馈/文章文件"""
    diary = vr.diary_summary(date)
    return {
        "date": date,
        "diary": diary,
        "review": qr.review_queue(),
        "score": qr.score_state(),
        "notes": vr.deeptutor_notes(date),
    }


@router.get("/plans")
def hub_plans(days: int = Query(7, ge=1, le=30)):
    """计划进度演进（日记「其余计划选项」+ 手机端自建计划）"""
    result = vr.plans_progress(days)
    for name, series in wr.plans_series(days).items():
        if name not in result["series"]:   # 同名时日记计划优先
            result["series"][name] = series
    return result


# ---------------------------------------------------------------- 写：任务勾选 / 复习完成 / 自建计划
class TaskToggleIn(BaseModel):
    date: str
    index: int
    done: bool


class ReviewDoneIn(BaseModel):
    concept: str


class PlanAddIn(BaseModel):
    name: str


class PlanToggleIn(BaseModel):
    id: str
    date: str
    done: bool


class PlanDeleteIn(BaseModel):
    id: str


@router.post("/task")
def hub_task_toggle(body: TaskToggleIn):
    """今日任务打勾/取消（写日记 checkbox，手机电脑同步）"""
    try:
        summary = wr.toggle_diary_checkbox(body.date, body.index, body.done)
    except wr.HubWriteError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "date": body.date, "diary": summary}


@router.post("/review-done")
def hub_review_done(body: ReviewDoneIn):
    """复习完成：日记写标记 + 即时推进艾宾浩斯间隔（幂等）"""
    try:
        return wr.review_done(body.concept)
    except wr.HubWriteError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/plan")
def hub_plan_add(body: PlanAddIn):
    """新增自建计划"""
    try:
        return {"ok": True, "plan": wr.plans_add(body.name)}
    except wr.HubWriteError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/plan-toggle")
def hub_plan_toggle(body: PlanToggleIn):
    """自建计划某日打卡/取消"""
    try:
        return {"ok": True, "plan": wr.plans_toggle(body.id, body.date, body.done)}
    except wr.HubWriteError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/plan-delete")
def hub_plan_delete(body: PlanDeleteIn):
    """删除自建计划"""
    try:
        wr.plans_delete(body.id)
        return {"ok": True}
    except wr.HubWriteError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/review")
def hub_review():
    """复习队列"""
    return qr.review_queue()


@router.get("/feedback")
def hub_feedback(n: int = Query(5, ge=1, le=20)):
    """最近 N 篇反馈摘要"""
    return {"items": vr.feedback_latest(n)}


@router.get("/library")
def hub_library():
    """收藏库统计"""
    return vr.library_stats()


@router.get("/state")
def hub_state():
    """系统状态：积分 + 公式轮换 + 休息日"""
    return {
        "score": qr.score_state(),
        "formula": qr.formula_rotation(),
        "skip_dates": qr.skip_dates(),
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- 网页热更新
def _web_version() -> int:
    try:
        return int(WEB_VERSION_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 1


def _web_files() -> list:
    """web_dist 下全部网页文件：返回 [{name, sha256}]。

    2026-10-18：热更新通道原先是「明文 HTTP + 无任何校验」——同网段改一份 JS
    就能写入 App 并拿到 window.Native 的全部原生能力。现在清单里带每文件
    sha256，客户端校验不通过就拒绝写入并回退内置资源。
    """
    if not WEB_DIST.exists():
        return []
    out = []
    for p in sorted(WEB_DIST.rglob("*")):
        if p.is_file() and p.name != "VERSION":
            try:
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                continue
            out.append({"name": p.relative_to(WEB_DIST).as_posix(), "sha256": digest})
    return out


@router.get("/webversion")
def hub_webversion():
    """网页版本 + 文件清单（含 sha256；App 启动时比对，有新版则逐文件拉取热更新）"""
    return {"version": _web_version(), "files": _web_files()}


@router.get("/webfile/{name:path}")
def hub_webfile(name: str):
    """网页文件内容（UTF-8 文本）"""
    if ".." in name or "\\" in name or ":" in name:
        raise HTTPException(status_code=400, detail="非法路径")
    p = (WEB_DIST / name).resolve()
    if not str(p).startswith(str(WEB_DIST.resolve())) or not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return {
        "name": name,
        "content": p.read_text(encoding="utf-8"),
        "version": _web_version(),
    }


# ---------------------------------------------------------------- AI Key 配置（PC 端填写）
class AiKeyIn(BaseModel):
    key: str = ""


def _ai_settings() -> dict:
    return _get_settings().get("ai", {}) or {}


@router.get("/aiconfig")
def hub_aiconfig():
    """AI Key 状态（不回传完整 Key）"""
    key = _ai_settings().get("deepseek_key", "")
    masked = (key[:3] + "***" + key[-4:]) if len(key) >= 10 else ("已配置" if key else "")
    return {"configured": bool(key), "masked": masked}


@router.put("/aiconfig")
def hub_aiconfig_put(body: AiKeyIn):
    """保存 / 清除 DeepSeek API Key（存本机 settings.json）"""
    key = (body.key or "").strip()
    if key and not re.match(r"^[A-Za-z0-9_\-]{8,}$", key):
        raise HTTPException(status_code=400, detail="Key 格式不正确")
    s = _get_settings()
    ai = dict(s.get("ai", {}))
    ai["deepseek_key"] = key
    s["ai"] = ai
    _save_settings({"ai": ai})
    return {"configured": bool(key)}


# ---------------------------------------------------------------- 网络信息（Tailscale 远程访问）
HUB_PORT = config.HUB_PORT   # 与 server/main.py SERVER_PORT 同源（M1a 配置化）

_NETINFO_CACHE = {"ts": 0.0, "tailscale": None}
NETINFO_TTL = 60.0   # 秒；Tailscale 地址不常变，缓存避免每请求都起子进程

# tailscale 可执行文件候选：PATH 优先，回退标准安装目录
# （某些受限环境会裁剪 PATH，导致裸命令名找不到）
_TAILSCALE_CANDIDATES = (
    "tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
)


def find_lan_ip() -> Optional[str]:
    """本机局域网 IP（UDP 探针，不实际发包）"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def find_tailscale_ip() -> Optional[str]:
    """Tailscale 虚拟网卡地址（100.x.x.x）；未安装 / 未登录返回 None。
    带 60s 缓存：tailscale 刚启动时最迟一分钟内会被发现。"""
    now = time.time()
    if now - _NETINFO_CACHE["ts"] < NETINFO_TTL:
        return _NETINFO_CACHE["tailscale"]
    ip = None
    for exe in _TAILSCALE_CANDIDATES:
        try:
            out = subprocess.run(
                [exe, "ip", "-4"],
                capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if out.returncode == 0:
                m = re.search(r"\b(100\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", out.stdout or "")
                if m:
                    ip = m.group(1)
                    break
        except Exception:
            continue
    _NETINFO_CACHE.update({"ts": now, "tailscale": ip})
    return ip


@router.get("/netinfo")
def hub_netinfo():
    """网络信息：局域网 IP + Tailscale 远程地址（手机跨网络同步用）。
    服务绑 0.0.0.0，两个地址都直达本机；remote_url 为空表示未安装 Tailscale。"""
    ts = find_tailscale_ip()
    return {
        "lan_ip": find_lan_ip(),
        "tailscale_ip": ts,
        "port": HUB_PORT,
        "remote_url": ("http://%s:%d" % (ts, HUB_PORT)) if ts else "",
    }
