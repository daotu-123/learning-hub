# -*- coding: utf-8 -*-
"""AI 助手（DeepSeek 对话 + 工作台上下文组装）（M1b-2 从 main.py 拆出）。

路由：
    POST /api/ai/chat      对话（Key 在 PC 端配置，见 /api/hub/aiconfig）
    GET  /api/ai/context   取当日的上下文文本

本模块是聚合叶子：为了组装上下文，它会 import 多个兄弟 router 的数据访问函数
（favorites / docs / usage / pomodoro / legacy_life / tasks）。
依赖方向是单向的（ai → 其它域），不成环；routers 之间不许 import main。
"""
import datetime
import json
import os
import re
import sqlite3
import urllib.request
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from common import SETTINGS_JSON, today_iso
from routers.docs import (deeptutor_daily, deeptutor_notes, diary_sync_state,
                          doc_read)
from routers.favorites import scan_favorites
from routers.legacy_life import health_daily, health_trend
from routers.pomodoro import pomodoro_daily
from routers.tasks import TASKS_DIR, parse_task_file
from routers.usage import hourly_daily, usage_conn, usage_trend

router = APIRouter(tags=["ai"])

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
        con = usage_conn()
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
        y_parts = [f"昨日({y_date})番茄{y_p['count']}个/专注{y_p['focus_min']}分钟"]
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
                    t = parse_task_file(p)
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


@router.post("/api/ai/chat")
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


@router.get("/api/ai/context")
def ai_context(date: str = Query(default_factory=today_iso)):
    return {"date": date, "context": _build_context(date)}
