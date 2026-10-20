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
from media_sign import MAX_TTL_SECONDS, signed

router = APIRouter(tags=["media"])

IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
# 可签名的三类媒体前缀。与 main.MEDIA_PREFIXES 必须一致（那边是**鉴权**用的，
# 这里是**签发**用的；两处分开写是刻意的——main 不能反向 import routers）。
ALLOWED_MEDIA_PREFIXES = ("/img/", "/photos/", "/api/hub/wallpapers/")
PHOTO_ROOT = OBSIDIAN_VAULT / "工作台照片"


class MediaSignIn(BaseModel):
    paths: list[str] = []


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
    # M2c-P3：媒体路径已纳入鉴权，返回给前端的必须是**带签名**的 URL。
    # 上传响应里的 url 会被前端直接塞进 <img src>，所以这里必须签。
    path = "/photos/" + "/".join(parts[1:])
    return {"ok": True, "path": str(p), "rel": rel,
            "url": path, "served": signed(path)["url"]}


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
                photo_path = "/photos/" + "/".join(parts[1:])
                photos.append({
                    "path": rel,
                    # path 是**规范化路径**（不含签名），供前端做 key 与去重；
                    # served 是可直接放进 <img src> 的短时签名 URL。
                    "path_url": photo_path,
                    "url": signed(photo_path)["url"],
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


# ---------------------------------------------------------------- 媒体签名下发
@router.post("/api/media/sign")
def media_sign_batch(payload: MediaSignIn):
    """把**规范化媒体路径**换成短时签名 URL。

    为什么需要它：日记里的 `![[图.png]]` 是用户正文，前端不能改写引用方式，
    而 <img src> 又没法带 Authorization 头。所以前端把路径发过来换签名，
    再把签名 URL 填进 src。

    **必须防路径穿越**：签名的意义是"授权访问这个确切路径"，
    如果这里能把 /photos/../ 之类签出去，就等于开了一个新的读取口。
    这里做逐条校验，任何一条不过就 400——整批失败，不做"跳过坏路径继续签"，
    因为那会让调用方误以为整批都拿到了可用的 URL。
    """
    out = []
    for raw in (payload.paths or [])[:200]:        # 上限 200，防止拿它当批量签发器
        p = str(raw).strip()
        if not p.startswith("/") or ".." in p or "\\" in p:
            raise HTTPException(status_code=400, detail="非法媒体路径: %r" % p[:80])
        if "?" in p or "#" in p:
            raise HTTPException(status_code=400, detail="媒体路径不得含 query/fragment")
        # 只认三条已知前缀，且必须以已知的图片扩展名结尾
        if not p.startswith(ALLOWED_MEDIA_PREFIXES):
            raise HTTPException(status_code=400, detail="不支持的媒体路径: %r" % p[:80])
        ext = os.path.splitext(p)[1].lower()
        if ext not in IMG_EXTS and ext not in PHOTO_EXTS:
            raise HTTPException(status_code=400, detail="不是允许的图片类型")
        out.append(signed(p))
    return {"items": out, "ttl": MAX_TTL_SECONDS}
