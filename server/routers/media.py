# -*- coding: utf-8 -*-
"""媒体：vault 通用图片服务 + 照片同步（M1b-2 从 main.py 拆出）。

路由：
    GET  /img/{path:path}         vault 内任意图片（日记里的 ![[路径]]）
    POST /api/photo/upload        上传照片（base64 → 工作台照片/月/）
    GET  /api/photos              照片列表（按月份过滤）
    GET  /photos/{month}/{name}   照片文件

按 Gate 0 §0.2「照片同步保留」，本域不属于 legacy_life。
"""
import base64 as b64
import datetime
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import OBSIDIAN_VAULT

router = APIRouter(tags=["media"])

IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
PHOTO_ROOT = OBSIDIAN_VAULT / "工作台照片"


class PhotoUpload(BaseModel):
    date: str
    name: str = "photo.jpg"
    data: str = ""   # base64 (可含 data:image/jpeg;base64, 前缀)


def _photo_path(date_str: str, name: str) -> Path:
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        d = datetime.date.today()
    month_dir = PHOTO_ROOT / f"{d.year}-{d.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    # 安全文件名: 时间戳 + 原扩展名
    ext = os.path.splitext(name)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        ext = ".jpg"
    fname = f"{datetime.datetime.now().strftime('%H%M%S')}_{d.isoformat()}{ext}"
    return month_dir / fname


@router.get("/img/{path:path}")
def vault_image(path: str):
    """通用 vault 图片服务: 日记里的 ![[路径]] 图片都能在手机上查看/下载"""
    if ".." in path or ":" in path or "\\" in path:
        raise HTTPException(status_code=400, detail="非法路径")
    p = OBSIDIAN_VAULT / path
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if p.suffix.lower() not in IMG_EXTS:
        raise HTTPException(status_code=400, detail="非图片文件")
    return FileResponse(str(p))


@router.post("/api/photo/upload")
def photo_upload(r: PhotoUpload):
    if not r.data:
        raise HTTPException(status_code=400, detail="无图片数据")
    payload = r.data
    if "," in payload and payload.startswith("data:"):
        payload = payload.split(",", 1)[1]
    try:
        raw = b64.b64decode(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="base64 解码失败")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="图片超过 20MB")
    p = _photo_path(r.date, r.name)
    p.write_bytes(raw)
    rel = str(p.relative_to(OBSIDIAN_VAULT)).replace("\\", "/")
    parts = rel.split("/")   # 工作台照片/月份/文件
    return {"ok": True, "path": str(p), "rel": rel,
            "url": "/photos/" + "/".join(parts[1:])}


@router.get("/api/photos")
def photos_list(month: str = "", limit: int = 200):
    """列出工作台照片, 按月份过滤, 最新的在前"""
    if not PHOTO_ROOT.exists():
        return {"photos": [], "months": []}
    months = sorted([d.name for d in PHOTO_ROOT.iterdir() if d.is_dir()], reverse=True)
    if month and month not in months:
        return {"photos": [], "months": months}
    targets = [PHOTO_ROOT / month] if month else [PHOTO_ROOT / m for m in months]
    photos = []
    for t in targets:
        if not t.exists():
            continue
        for f in sorted(t.iterdir(), reverse=True):
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                rel = str(f.relative_to(OBSIDIAN_VAULT)).replace("\\", "/")
                parts = rel.split("/")
                photos.append({
                    "path": rel,
                    "url": "/photos/" + "/".join(parts[1:]),
                    "month": parts[1],
                    "name": f.name,
                    "size": f.stat().st_size,
                })
    photos.sort(key=lambda p: p["path"], reverse=True)
    return {"photos": photos[:limit], "months": months}


@router.get("/photos/{month}/{name}")
def photo_file(month: str, name: str):
    if "/" in name or "\\" in name or ".." in name or "/" in month or ".." in month:
        raise HTTPException(status_code=400, detail="非法路径")
    p = PHOTO_ROOT / month / name
    if not p.exists():
        raise HTTPException(status_code=404, detail="照片不存在")
    return FileResponse(str(p))
