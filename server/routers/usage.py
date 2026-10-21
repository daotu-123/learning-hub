# -*- coding: utf-8 -*-
"""手机使用时间统计（M1b-2 从 main.py 拆出）。

路由：
    GET  /api/usage   近 N 天使用趋势
    POST /api/usage   上报当日应用列表 + 小时活跃度
"""
import sqlite3
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

import usage_db

router = APIRouter(tags=["usage"])


def _usage_conn():
    # 建表逻辑已统一收到 usage_db.connect()，不在这里重复 CREATE TABLE。
    # 原来这里只建 usage / usage_hourly 两张表，而 pomodoro / health 由别的域
    # 各自建——首启时按请求顺序不同，某些表会缺失（见 usage_db.py 顶部说明）。
    return usage_db.connect()


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


# 供 ai 域复用（下划线开头是模块私有约定，这里显式导出公共别名）
usage_conn = _usage_conn


class UsageReport(BaseModel):
    date: str
    apps: List[dict] = []
    hourly: List[dict] = []   # [{hour, seconds}] 今日按小时活跃分布


@router.get("/api/usage")
def usage(days: int = 7):
    return usage_trend(days)


@router.post("/api/usage")
def usage_post(report: UsageReport):
    usage_save(report.date, report.apps)
    hourly_save(report.date, report.hourly)
    return {"ok": True, "date": report.date, "apps": len(report.apps)}
