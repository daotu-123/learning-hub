# -*- coding: utf-8 -*-
"""健康模块（睡眠 / 运动）—— **Gate 0 §0.5 登记待删，下一轮删除。**

路由：
    POST /api/health   记录一条睡眠/运动
    GET  /api/health   当日明细或近 N 天趋势

为什么单独立一个文件：按 docs/gate0-decisions.md §0.5，数据源是手环、
App 不再承担记录与展示，本模块连同 usage.db 的 health 表一起要删。
单独放是为了让下一轮的删除动作只碰一个文件 + main.py 的一行 include，
不会牵连别的域。

注意：表与历史数据**不删**（§0.5 明确"保留表与历史数据不删"），
删除时只停读写。删表有数据风险，无收益。
"""
import datetime
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import usage_db

router = APIRouter(tags=["legacy-life"])


def _health_conn():
    # health 表的建表语句统一在 usage_db.SCHEMA（§0.5 说表与数据保留，
    # 所以语句还在，只是不再在这里重复）
    return usage_db.connect()


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


class HealthReport(BaseModel):
    date: str
    kind: str            # sleep | exercise
    label: str = ""
    value_min: int = 0
    start_ts: str = ""
    end_ts: str = ""


@router.post("/api/health")
def health_post(r: HealthReport):
    if r.kind not in ("sleep", "exercise"):
        raise HTTPException(status_code=400, detail="kind 必须是 sleep 或 exercise")
    health_save(r.date, r.kind, r.label, r.value_min, r.start_ts, r.end_ts)
    return {"ok": True, "date": r.date, "kind": r.kind}


@router.get("/api/health")
def health_get(date: str = Query(default_factory=lambda: datetime.date.today().isoformat()),
               days: int = 0):
    if days > 0:
        return health_trend(days)
    return health_daily(date)
