# -*- coding: utf-8 -*-
"""
Learning Hub: writer —— 学习中枢唯一写入口
- toggle_diary_checkbox   今日任务打勾（写 Obsidian 日记）
- review_done             复习完成（日记写 `复习完成：{名称}` 标记 + 立即推进
                          review_queue.json 艾宾浩斯间隔，与 homework_sync 同口径）
- 自定义计划 CRUD          data/plans.json（手机端自建计划，打卡同步）

写安全约定：
1. 每次写文件前先备份到 data/backups/<时间戳>/（保留最近 30 份）
2. 临时文件 + os.replace 原子替换，避免写一半
3. 复习推进带 last_review_day 幂等保护，与每日脚本重复执行不冲突
"""
import datetime
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional

from . import vault_reader as vr

# M1a：data 目录改由 config 单一来源（原为本文件硬编码）
from config import DATA_DIR

BACKUP_ROOT = DATA_DIR / "backups"
MAX_BACKUPS = 30
PLANS_JSON = DATA_DIR / "plans.json"
REVIEW_QUEUE = Path(r"E:\soft_files\tools\hermes-scripts\review_queue.json")

# 与 vault_reader.parse_checkboxes / 前端 parseTasks 同一行格式，保序号对齐
CHECKBOX_LINE_RE = re.compile(r"^(\s*[-*]\s*\[)([ xX])(\]\s*.*)$")


class HubWriteError(Exception):
    """可展示给用户的写操作错误（router 转 400）"""


# ---------------------------------------------------------------- 备份 / 原子写
def _backup(path: Path) -> None:
    if not path.exists():
        return
    try:
        BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        bdir = BACKUP_ROOT / stamp
        bdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, bdir / path.name)
        dirs = sorted(d for d in BACKUP_ROOT.iterdir() if d.is_dir())
        while len(dirs) > MAX_BACKUPS:
            shutil.rmtree(dirs.pop(0), ignore_errors=True)
    except Exception:
        pass  # 备份失败不阻断主流程（原文件未动）


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------- 今日任务勾选
def toggle_diary_checkbox(date_str: str, index: int, done: bool) -> dict:
    """切换日记中第 index 个（0 基）checkbox 的完成态，返回当日摘要。

    index 与前端 parseTasks() 的输出顺序一一对应（均按文档顺序全量匹配）。
    """
    if index < 0:
        raise HubWriteError("任务序号不合法")
    p = vr.diary_path(date_str)
    if p is None:
        raise HubWriteError("这一天还没有日记，先去电脑端或 Obsidian 建一篇")
    text = _read_text(p)
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    seen = -1
    target = None
    for i, line in enumerate(lines):
        if CHECKBOX_LINE_RE.match(line):
            seen += 1
            if seen == index:
                target = i
                break
    if target is None:
        raise HubWriteError("第 %d 个任务不存在" % (index + 1))
    m = CHECKBOX_LINE_RE.match(lines[target])
    cur_done = m.group(2).strip().lower() == "x"
    if cur_done != done:
        lines[target] = m.group(1) + ("x" if done else " ") + m.group(3)
        _backup(p)
        _atomic_write(p, eol.join(lines) + eol)
    return vr.diary_summary(date_str)


# ---------------------------------------------------------------- 复习完成
def _next_interval(current: int, wrong: bool = False) -> int:
    """艾宾浩斯间隔推进（与 homework_sync.next_interval 完全一致）"""
    base = [1, 2, 4, 7, 15, 30] if wrong else [7, 15, 30, 60]
    for v in base:
        if current < v:
            return v
    return current * 2


def _append_review_marker(date_str: str, concept: str) -> bool:
    """日记末尾追加 `- 复习完成：{concept}`（幂等），返回是否实际写入。

    标记是给 PC 端每日脚本（homework_sync.advance_completed_reviews）看的，
    保证 App 勾选与手写在日记里走同一条推进链路。
    """
    p = vr.diary_path(date_str)
    if p is None:
        return False  # 没有日记则只推进队列，不强行建文件
    text = _read_text(p)
    pat = re.compile(r"复习完成\s*[：:]\s*" + re.escape(concept) + r"\s*$", re.M)
    if pat.search(text):
        return False
    eol = "\r\n" if "\r\n" in text else "\n"
    new = text.rstrip("\r\n") + eol
    if "## ✅ 复习打卡" not in text:
        new += eol + "---" + eol + eol + "## ✅ 复习打卡（App 同步）" + eol + eol
    new += "- 复习完成：" + concept + eol
    _backup(p)
    _atomic_write(p, new)
    return True


def _advance_review_item(concept: str, today: datetime.date) -> tuple:
    """推进单条复习（同 homework_sync.advance_completed_reviews 口径）。
    返回 (命中条目 dict 或 None, 今天是否已推进过)。"""
    if not REVIEW_QUEUE.exists():
        return None, False
    q = json.loads(REVIEW_QUEUE.read_text(encoding="utf-8"))
    hit = None
    already = False
    for it in q.get("items", []):
        if it.get("status") != "active":
            continue
        name = it.get("concept", "")
        if not (concept == name or (concept and concept in name)):
            continue
        if it.get("last_review_day") == today.isoformat():
            already = True
            hit = it
            break
        it["last_review_day"] = today.isoformat()
        wrong = "错题" in name
        it["interval_days"] = _next_interval(it.get("interval_days", 7), wrong)
        it["next_review"] = (today + datetime.timedelta(days=it["interval_days"])).isoformat()
        it["reviews"] = it.get("reviews", 0) + 1
        hit = it
        break
    if hit and not already:
        _backup(REVIEW_QUEUE)
        REVIEW_QUEUE.write_text(
            json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    return hit, already


def review_done(concept: str) -> dict:
    """复习完成：写日记标记 + 即时推进间隔（幂等，可重复点）"""
    concept = (concept or "").strip()
    if not concept or len(concept) > 200:
        raise HubWriteError("复习名称不合法")
    today = datetime.date.today()
    marker_written = _append_review_marker(today.isoformat(), concept)
    item, already = _advance_review_item(concept, today)
    return {
        "ok": True,
        "concept": concept,
        "marker_written": marker_written,
        "already": already,
        "item": item,
    }


# ---------------------------------------------------------------- 自定义计划
def plans_load() -> list:
    if not PLANS_JSON.exists():
        return []
    try:
        data = json.loads(PLANS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    plans = data.get("plans", []) if isinstance(data, dict) else []
    return [p for p in plans if isinstance(p, dict) and p.get("id") and p.get("name")]


def _save_plans(plans: list) -> None:
    _backup(PLANS_JSON)
    _atomic_write(PLANS_JSON, json.dumps(
        {"plans": plans}, ensure_ascii=False, indent=2))


def plans_add(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise HubWriteError("计划名不能为空")
    if len(name) > 40:
        raise HubWriteError("计划名最长 40 字")
    plans = plans_load()
    if any(p["name"] == name for p in plans):
        raise HubWriteError("已有同名计划")
    p = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "created": datetime.date.today().isoformat(),
        "checkins": {},
    }
    plans.append(p)
    _save_plans(plans)
    return p


def plans_toggle(plan_id: str, date_str: str, done: bool) -> dict:
    try:
        datetime.date.fromisoformat(date_str)
    except ValueError:
        raise HubWriteError("日期不合法")
    plans = plans_load()
    for p in plans:
        if p["id"] == plan_id:
            ck = p.setdefault("checkins", {})
            if done:
                ck[date_str] = True
            else:
                ck.pop(date_str, None)
            _save_plans(plans)
            return p
    raise HubWriteError("计划不存在")


def plans_delete(plan_id: str) -> bool:
    plans = plans_load()
    left = [p for p in plans if p["id"] != plan_id]
    if len(left) == len(plans):
        raise HubWriteError("计划不存在")
    _save_plans(left)
    return True


def plans_series(days: int) -> dict:
    """自建计划的 N 日序列（与日记计划同结构，带 custom 标记）"""
    today = datetime.date.today()
    out = {}
    for p in plans_load():
        series = []
        for i in range(days):
            d = today - datetime.timedelta(days=days - 1 - i)
            ds = d.isoformat()
            ok = bool(p.get("checkins", {}).get(ds))
            series.append({
                "date": ds,
                "progress": "已完成" if ok else "",
                "done": ok,
                "custom": True,
                "id": p["id"],
            })
        out[p["name"]] = series
    return out
