# -*- coding: utf-8 -*-
"""健康检查端点（M1a）。

- `GET /health/live`  进程存活探针：不碰任何依赖，永不鉴权
- `GET /health/ready` 依赖就绪探针：data 目录可写 + usage.db 可读

两条都在 `/api/` 之外，因此**本来就不进鉴权中间件**（中间件只拦 `/api/` 开头）。
这里显式写测试锁定该性质：以后若把中间件扩大到全部路径，测试会先炸。

与 `/api/health`（睡眠/运动记录，属健康模块）不是一回事：那两条是业务读写，
按 Gate 0 §0.5 留到后续阶段处理，本文件不复用、不改动它们。

响应形状（承重，别改成 HTTPException）：
    就绪 200 {"status":"ok","checks":{...}}
    不就绪 503 {"status":"fail","checks":{...}}
`/health/ready` 直接返回 JSONResponse 而不抛 HTTPException，否则会被统一错误
处理器改形状，探针就拿不到 checks 明细了。
"""
import sqlite3
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import DATA_DIR, USAGE_DB

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live():
    """存活：只要进程能回包就是 200。"""
    return {"status": "ok"}


def _check_data_dir() -> dict:
    """data 目录可写：建一个自己的探针文件再删掉，不碰任何用户数据。"""
    probe = DATA_DIR / ".health_probe"
    try:
        probe.touch()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def _check_usage_db() -> dict:
    """usage.db 可读：以只读模式打开。

    文件不存在视为就绪——首启时库还没建（pomodoro 表是首次写入时才 CREATE），
    为此让 ready 失败属于误报。
    """
    if not USAGE_DB.exists():
        return {"ok": True, "detail": "absent"}
    try:
        con = sqlite3.connect(f"file:{USAGE_DB.as_posix()}?mode=ro", uri=True)
        try:
            con.execute("SELECT 1").fetchone()
        finally:
            con.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


@router.get("/health/ready")
def ready():
    checks = {"data_dir": _check_data_dir(), "usage_db": _check_usage_db()}
    ok = all(c.get("ok") for c in checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "fail", "checks": checks},
    )
