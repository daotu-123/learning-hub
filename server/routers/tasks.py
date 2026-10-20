# -*- coding: utf-8 -*-
"""Obsidian Tasks 插件格式的任务增删改查（M1b-2 从 main.py 拆出）。

路由：
    GET  /api/tasks
    POST /api/tasks/add
    POST /api/tasks/patch
"""
import datetime
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from common import parse_frontmatter, touch_modified
from config import OBSIDIAN_VAULT

router = APIRouter(tags=["tasks"])

TASKS_DIR = OBSIDIAN_VAULT / "TaskNotes" / "Tasks"


def parse_task_file(p: Path) -> dict:
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


@router.get("/api/tasks")
def tasks_get():
    if not TASKS_DIR.exists():
        return {"tasks": [], "server_ts": 0}
    tasks = []
    for p in sorted(TASKS_DIR.glob("*.md")):
        try:
            tasks.append(parse_task_file(p))
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


@router.post("/api/tasks/add")
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
    return {"ok": True, "task": parse_task_file(p)}


@router.post("/api/tasks/patch")
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
            "task": parse_task_file(p),
        })
    if upd.action == "delete":
        p.unlink()
        return {"ok": True, "deleted": upd.file}
    text = p.read_text(encoding="utf-8", errors="ignore")
    if upd.action == "toggle" and upd.done is not None:
        new_status = "done" if upd.done else "open"
        if re.search(r"^status:.*$", text, flags=re.M):
            text = re.sub(r"^status:.*$", f"status: {new_status}", text, count=1, flags=re.M)
        text = touch_modified(text)
    elif upd.action == "timeEntry" and upd.start_ts and upd.end_ts:
        entry = (f"  - startTime: {upd.start_ts}\n"
                 f"    description: Work session\n"
                 f"    endTime: {upd.end_ts}\n")
        if "timeEntries:" in text:
            text = text.rstrip() + "\n" + entry + "\n"
        else:
            text = text.rstrip() + "\n\ntimeEntries:\n" + entry + "\n"
        text = touch_modified(text)
    else:
        raise HTTPException(status_code=400, detail="未知操作")
    p.write_text(text, encoding="utf-8")
    return {"ok": True, "task": parse_task_file(p)}
