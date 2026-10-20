# -*- coding: utf-8 -*-
"""身份端点（M2a）：/api/auth/login | logout | me | password。

挂在现有 /api/auth 下，因此 /api/v1/auth/* 由 M1c 的改写中间件自动覆盖。

**这些端点的鉴权口径与全局鉴权中间件不同，这是 owner 2026-10-20 定的边界：**

全局 auth_guard 认三种凭据（回环 / 旧共享令牌 / 会话令牌）；
而 logout / me / password 操作的是"某个会话"，因此**只认会话令牌**：
  - 旧共享令牌 → 401。共享令牌不是会话（不可撤销、无 TTL、不代表身份），
    让它能调 /me 会造成权限混淆（"me"是谁？）。
  - 回环且无会话 → 401。回环豁免是为了让静态页面能打开，不是为了让任何人
    拿到账号信息。
  - 会话无效（过期 / 撤销 / 伪造）→ 401，**与"没带令牌"同一形状**，不泄露原因。

401 的响应体与 legacy 逐字节一致（见 auth_sessions.UNAUTHORIZED_BODY）。
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auth_sessions import (
    MIN_PASSWORD_LENGTH,
    NO_ACCOUNT_MESSAGE,
    check_login,
    create_session,
    load_account,
    revoke_session,
    session_expires_at,
    session_token_from_request,
    set_password,
    unauthorized_response,
    validate_session,
    verify_password,
)

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


def _require_session(request: Request):
    """取出并校验会话令牌。失败返回 None（由调用方返回 legacy 401）。"""
    token = session_token_from_request(request)
    rec = validate_session(token)
    if rec is None:
        return None
    return token, rec


def _current_username(rec: dict) -> str:
    """会话主体名：优先取会话记录里存的，回落到账号文件。"""
    return (rec.get("username") or "") or (load_account().get("username") or "")


# ---------------------------------------------------------------- 登录
@router.post("/api/auth/login")
def login(payload: LoginIn, request: Request):
    """口令登录换取会话令牌。

    - 没有账号 → 503 + 指引（服务本身照常运行，CLI 引导建账号）
    - 口令错 / 用户名不存在 → 同一个 401、同一条消息，耗时也一致
    - 响应里的 token 是**明文**，只在这里出现一次；服务端只存哈希
    """
    if not (load_account().get("password_hash") or "").strip():
        raise HTTPException(status_code=503, detail=NO_ACCOUNT_MESSAGE)

    if not check_login(payload.username, payload.password):
        # 用户名不存在与口令错走同一条路径：同一条消息、同一个状态码。
        raise HTTPException(status_code=401, detail="用户名或口令错误")

    token, rec = create_session(
        user_agent=request.headers.get("user-agent", ""),
        username=load_account().get("username") or payload.username,
    )
    return {
        "token": token,
        "expires_at": session_expires_at(rec),
        "username": _current_username(rec),
    }


# ---------------------------------------------------------------- 注销
@router.post("/api/auth/logout")
def logout(request: Request):
    """撤销当前会话。"""
    got = _require_session(request)
    if got is None:
        return unauthorized_response()
    token, _rec = got
    revoke_session(token)
    return {"ok": True}


# ---------------------------------------------------------------- 当前身份
@router.get("/api/auth/me")
def me(request: Request):
    """当前会话是谁。"""
    got = _require_session(request)
    if got is None:
        return unauthorized_response()
    _token, rec = got
    return {
        "username": _current_username(rec),
        "created_at": rec.get("created_at"),
        "expires_at": session_expires_at(rec),
    }


# ---------------------------------------------------------------- 改口令
@router.put("/api/auth/password")
def change_password(payload: PasswordIn, request: Request):
    """改口令，并撤销该账号的全部旧会话。

    成功后**返回一个新会话**（形状同 login），这样调用方不会因为自己的
    改口令操作被踢下线。owner 2026-10-20 授权由本轮自行决定，此处即该决定。
    """
    got = _require_session(request)
    if got is None:
        return unauthorized_response()
    _token, rec = got

    if not verify_password(payload.old_password):
        raise HTTPException(status_code=401, detail="原口令不正确")
    if len(payload.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail="新口令至少 %d 位" % MIN_PASSWORD_LENGTH,
        )

    username = _current_username(rec)
    # 先改口令（内部会撤销全部会话），再给调用方发一个新的
    set_password(username, payload.new_password, revoke_sessions=True)
    token, new_rec = create_session(
        user_agent=request.headers.get("user-agent", ""),
        username=username,
    )
    return {
        "token": token,
        "expires_at": session_expires_at(new_rec),
        "username": username,
    }
