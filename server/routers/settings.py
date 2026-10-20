# -*- coding: utf-8 -*-
"""工作台设置（M1b-2 从 main.py 拆出）。

路由：
    GET  /api/settings   读全局 settings.json
    PUT  /api/settings   合并写 settings.json

设置读写实现在 common.py（auth_token 也要用，不能让 routers 依赖 main）。
"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from common import get_settings, save_settings

router = APIRouter(tags=["settings"])


class SettingsPatch(BaseModel):
    background: Optional[str] = None
    accent: Optional[str] = None
    theme: Optional[str] = None


@router.get("/api/settings")
def settings_get():
    return get_settings()


@router.put("/api/settings")
def settings_put(patch: SettingsPatch):
    return save_settings(patch.dict(exclude_none=True))
