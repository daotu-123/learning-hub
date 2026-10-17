# -*- coding: utf-8 -*-
"""
Learning Hub: queue_reader
读取 F 盘 hermes-scripts 的账本文件（只读）
- review_queue.json   艾宾浩斯复习队列
- score_state.json    积分状态
- formula_rotation.json 公式轮换
- skip_dates.json     休息日
"""
import json
import datetime
from pathlib import Path
from typing import List, Dict, Optional

HERMES_SCRIPTS = Path(r"E:\soft_files\tools\hermes-scripts")


def _load(name: str) -> Optional[Dict]:
    p = HERMES_SCRIPTS / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def review_queue() -> Dict:
    """复习队列：按状态分组 + 到期统计"""
    data = _load("review_queue.json")
    if not data or "items" not in data:
        return {"total": 0, "active": 0, "done": 0, "due_today": 0, "items": []}
    items = data["items"]
    today = datetime.date.today().isoformat()
    active, done, due = [], [], []
    for it in items:
        status = it.get("status", "active")
        item = {
            "concept": it.get("concept", ""),
            "source_ref": it.get("source_ref", ""),
            "interval_days": it.get("interval_days", 1),
            "next_review": it.get("next_review", ""),
            "reviews": it.get("reviews", 0),
            "status": status,
            "added": it.get("added", ""),
        }
        if status == "done":
            done.append(item)
        else:
            active.append(item)
            if item["next_review"] and item["next_review"] <= today:
                due.append(item)
    active.sort(key=lambda x: (x["next_review"], -x["reviews"]))
    return {
        "total": len(items),
        "active": len(active),
        "done": len(done),
        "due_today": len(due),
        "due": due[:15],
        "active_items": active[:40],
    }


def score_state() -> Dict:
    data = _load("score_state.json") or {}
    return {
        "date": data.get("date", ""),
        "total": data.get("total", 0),
        "earned": data.get("earned", 0),
        "deducted": data.get("deducted", 0),
    }


def formula_rotation() -> Dict:
    data = _load("formula_rotation.json") or {}
    return {
        "math": data.get("math", 0),
        "mech": data.get("mech", 0),
    }


def skip_dates() -> List[str]:
    data = _load("skip_dates.json") or {}
    return data.get("dates", [])
