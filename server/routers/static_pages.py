# -*- coding: utf-8 -*-
"""静态页与静态资源（M1b-2 从 main.py 拆出）。

路由（注册顺序敏感，勿调）：
    GET /hub              旧版学习中枢入口页
    GET /server.js        旧页公共模块
    GET /hub/{path:path}  旧页静态资源
    GET /app              新版单 App SPA 入口
    GET /app/{path:path}  SPA 静态资源

`/hub` 必须排在 `/hub/{path:path}` 前、`/app` 必须排在 `/app/{path:path}` 前
（tests/test_routers.py 有断言锁顺序）。
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config import HUB_ROOT

router = APIRouter(tags=["static"])

HUB_WEB = HUB_ROOT / "server" / "hub_web"
if not HUB_WEB.exists() and getattr(sys, "frozen", False):
    # PyInstaller 打包运行时：磁盘路径缺失时回退到包内资源（hub_web 随 --add-data 打入）
    HUB_WEB = Path(sys._MEIPASS) / "hub_web"

APP_DIST = HUB_ROOT / "server" / "web_dist" / "app"
if not APP_DIST.exists() and getattr(sys, "frozen", False):
    APP_DIST = Path(sys._MEIPASS) / "web_dist" / "app"


def _media_of(path: str):
    if path.endswith(".js"):
        return "text/javascript"
    if path.endswith(".css"):
        return "text/css"
    if path.endswith(".html"):
        return "text/html"
    if path.endswith(".json"):
        return "application/json"
    return None


@router.get("/hub")
def hub_page():
    """学习中枢入口页"""
    p = HUB_WEB / "hub.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="hub.html 未构建")
    return FileResponse(str(p))


@router.get("/server.js")
def server_js():
    """公共服务器模块（学习中枢页引用）"""
    p = HUB_WEB / "server.js"
    if not p.exists():
        raise HTTPException(status_code=404, detail="server.js 未部署")
    return FileResponse(str(p), media_type="application/javascript")


@router.get("/hub/{path:path}")
def hub_assets(path: str):
    """学习中枢静态资源（css/js）"""
    if ".." in path or "\\" in path or ":" in path:
        raise HTTPException(status_code=400, detail="非法路径")
    p = HUB_WEB / path
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(str(p))


@router.get("/app")
def app_index():
    """新版单 App 入口（SPA index.html）"""
    p = APP_DIST / "index.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="SPA 未构建：请先在 web/ 目录执行 npm run build")
    return FileResponse(str(p))


@router.get("/app/{path:path}")
def app_assets(path: str):
    """SPA 静态资源（hash 路由，无需服务端回退）"""
    if not path:
        path = "index.html"          # /app/ 与 /app 都落到入口
    if ".." in path or "\\" in path or ":" in path:
        raise HTTPException(status_code=400, detail="非法路径")
    p = APP_DIST / path
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(str(p), media_type=_media_of(path))
