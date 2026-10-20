# -*- coding: utf-8 -*-
"""番茄钟（M1b-2 从 main.py 拆出）。

路由：
    POST /api/pomodoro   记录一个完成的番茄钟
    GET  /api/pomodoro   当日番茄钟汇总

注：hub 域另有一份 /api/hub/focus（近 N 天趋势），按 Gate 0 §0.2
「番茄钟保留、只留一份」的决策，后续以 hub 为主，本域是旧入口。
"""
import datetime
import sqlite3

from fastapi import APIRouter, Query
from pydantic import BaseModel

from common import today_iso
from config import USAGE_DB

router = APIRouter(tags=["pomodoro"])


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


class PomoReport(BaseModel):
    date: str
    task: str = ""
    minutes: int = 25


@router.post("/api/pomodoro")
def pomodoro_post(report: PomoReport):
    pomodoro_save(report.date, report.task, report.minutes)
    return {"ok": True, "date": report.date}


@router.get("/api/pomodoro")
def pomodoro_get(date: str = Query(default_factory=today_iso)):
    return pomodoro_daily(date)
