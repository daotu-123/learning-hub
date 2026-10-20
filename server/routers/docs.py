# -*- coding: utf-8 -*-
"""文档域：工作台日报 / vault 文档读写 / 日记同步 / DeepTutor 活动与笔记
（M1b-2 从 main.py 拆出）。

路由（注册顺序）：
    POST /api/daily-report      写 Obsidian 工作台日报
    GET  /api/daily-report      读日报是否存在
    GET  /api/doc               读 vault 文档（diary|weekly|monthly）
    PUT  /api/doc               写 vault 文档（带 mtime 冲突保护）
    GET  /api/diary             日记同步状态
    PUT  /api/diary             写日记（带 mtime 冲突保护）
    GET  /api/deeptutor/notes   Obsidian deeptutor/ 下当日新增
    GET  /api/deeptutor         DeepTutor chat_history.db + 日志汇总

被其它域复用的数据访问函数（ai.py 的上下文组装会 import 它们）：
    deeptutor_daily / deeptutor_notes / diary_sync_state / doc_read
"""
import datetime
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from common import md5_text, month_dir_name, today_iso
from config import DEEPTUTOR_DIR, OBSIDIAN_VAULT

router = APIRouter(tags=["docs"])

DIARY_ROOT = OBSIDIAN_VAULT / "日记"
DEEPTUTOR_DB = DEEPTUTOR_DIR / "chat_history.db"
DEEPTUTOR_LOG = DEEPTUTOR_DIR / "logs" / "deeptutor.jsonl"


# ---------------------------------------------------------------- 日记
def diary_path(date_str: str) -> Optional[Path]:
    """按 Obsidian 日记目录规则定位文件"""
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        return None
    month_dir = DIARY_ROOT / month_dir_name(d)
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
        "hash": md5_text(content),
        "content": content,
    }


def write_diary(date_str: str, content: str) -> Path:
    """写入/更新 Obsidian 当日日记, 自动建月份目录"""
    d = datetime.date.fromisoformat(date_str)
    month_dir = DIARY_ROOT / month_dir_name(d)
    month_dir.mkdir(parents=True, exist_ok=True)
    p = month_dir / f"{date_str}.md"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------- vault 文档
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
        "hash": md5_text(content),
        "content": content, "path": str(p),
    }


def doc_write(dtype: str, key: str, content: str) -> Path:
    p = doc_path(dtype, key)
    if p is None:
        raise HTTPException(status_code=400, detail="文档类型或标识不合法")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------- DeepTutor
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


# ---------------------------------------------------------------- 路由
class DailyReport(BaseModel):
    date: str
    content: str


class DocUpdate(BaseModel):
    dtype: str           # diary | weekly | monthly
    key: str
    content: str
    base_updated_at: float = 0.0


class DiaryUpdate(BaseModel):
    date: str
    content: str
    base_updated_at: float = 0.0   # 客户端上次拉取时的服务器 mtime
    client_updated_at: float = 0.0  # 客户端本地最后修改时间


@router.post("/api/daily-report")
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


@router.get("/api/daily-report")
def daily_report_get(date: str):
    try:
        d = datetime.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")
    p = OBSIDIAN_VAULT / "工作台日报" / f"{d.isoformat()}.md"
    if not p.exists():
        return {"exists": False, "date": date}
    return {"exists": True, "date": date, "path": str(p)}


@router.get("/api/doc")
def doc_get(dtype: str, key: str):
    return doc_read(dtype, key)


@router.put("/api/doc")
def doc_put(upd: DocUpdate):
    cur = doc_read(upd.dtype, upd.key)
    if cur["exists"] and upd.base_updated_at > 0 and cur["mtime"] > upd.base_updated_at + 1:
        raise HTTPException(status_code=409, detail={
            "message": "PC 端文档已被修改, 存在冲突",
            "server": cur,
        })
    p = doc_write(upd.dtype, upd.key, upd.content)
    return {"ok": True, "path": str(p), "mtime": p.stat().st_mtime}


@router.get("/api/diary")
def diary_get(date: str = Query(default_factory=today_iso)):
    return diary_sync_state(date)


@router.put("/api/diary")
def diary_put(upd: DiaryUpdate):
    cur = diary_sync_state(upd.date)
    if cur["exists"] and upd.base_updated_at > 0 and cur["mtime"] > upd.base_updated_at + 1:
        raise HTTPException(status_code=409, detail={
            "message": "PC 端日记已被修改, 存在冲突",
            "server": cur,
        })
    p = write_diary(upd.date, upd.content)
    return {"ok": True, "path": str(p), "mtime": p.stat().st_mtime}


@router.get("/api/deeptutor/notes")
def deeptutor_notes_api(date: str = Query(default_factory=today_iso)):
    return deeptutor_notes(date)


@router.get("/api/deeptutor")
def deeptutor(date: str = Query(default_factory=today_iso)):
    return deeptutor_daily(date)
