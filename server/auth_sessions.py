# -*- coding: utf-8 -*-
"""身份体系（M2a）：单账号 + Argon2id 口令 + 服务端会话令牌。

owner 2026-10-20 的四个决定：
  1. 登录方式：单账号 + 口令，Argon2id 存哈希。首版不做 TOTP。
  2. 令牌形态：客户端用 `Authorization: Bearer <session>`（也接受 X-Token 头携带
     会话令牌）。**会话令牌只走请求头，绝不接受 query 参数。**
  3. 账号创建：CLI 引导（`python manage.py set-password`），Argon2id 哈希写进数据目录。
  4. 双轨过渡：旧的共享令牌（X-Token / ?token=）继续有效，直到新版 APK 铺开。

本模块是身份的唯一事实来源，负责：
  - 账号存储（account.json，只存 Argon2id 哈希，绝不存明文口令）
  - 会话存储（sessions.json，**只存令牌哈希**，明文令牌只在登录响应里出现一次）
  - 口令与会话的校验、滑动 TTL、绝对上限、撤销
  - legacy 401 响应体（见 UNAUTHORIZED_BODY）

设计要点：
  - **令牌哈希用 SHA-256 而不是 Argon2**：会话令牌是 secrets.token_urlsafe(32)
    生成的 256 位高熵随机串，没有字典攻击面；Argon2 是给低熵口令用的，
    对随机令牌反而是无谓的 CPU 开销（每个请求都要算）。
  - **账号不存在时也要做一次等价 Argon2 运算**，抹平"用户不存在"与"口令错"的
    耗时差，避免账号枚举 oracle。
  - **不泄露原因**：会话失效（过期/撤销/伪造）与"没带令牌"返回完全相同的响应体。
  - 写盘用 tmp + os.replace 原子替换（与 hub/writer.py 同一套习惯）。
    刻意**不做备份**：account.json 只存哈希，丢了用 CLI 重建即可；sessions.json
    丢了只是全部会话失效。备份会把凭证材料复制进 backups/，得不偿失。
"""
import datetime
import hashlib
import json
import os
import secrets
import threading
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from config import DATA_DIR

# 与 hub/writer.py 的 PLANS_JSON 同一套路：config 给出数据目录，模块自己派生文件路径
ACCOUNT_JSON = DATA_DIR / "account.json"
SESSIONS_JSON = DATA_DIR / "sessions.json"

# ---------------------------------------------------------------- 口令
MIN_PASSWORD_LENGTH = 12
_HASHER = PasswordHasher()          # Argon2id 默认参数（m=64MiB, t=3, p=4）

_dummy_lock = threading.Lock()
_dummy_hash = None


def _dummy_verify(password: str) -> None:
    """对不存在的账号也跑一次 Argon2 校验，让耗时与"口令错"一致。"""
    global _dummy_hash
    with _dummy_lock:
        if _dummy_hash is None:
            _dummy_hash = _HASHER.hash(secrets.token_urlsafe(32))
    try:
        _HASHER.verify(_dummy_hash, password)
    except Exception:
        pass


# ---------------------------------------------------------------- 会话
SESSION_TOKEN_BYTES = 32            # secrets.token_urlsafe(32) → 43 字符
SLIDING_TTL_SECONDS = 7 * 24 * 3600     # 滑动 TTL：闲置 7 天即失效
ABSOLUTE_TTL_SECONDS = 30 * 24 * 3600   # 绝对上限：创建后 30 天必失效
SESSION_TOUCH_INTERVAL = 5 * 60     # last_seen_at 的更新粒度，避免每个请求都写盘

# legacy 401 响应体。抽成常量是为了 main.py 的鉴权中间件与 routers/auth.py 的
# 会话校验共用同一份，从根上杜绝"两边写法不同 → 字节不一致"。
#
# M2b 唯一一次**主动**改动 hint 文案（owner 授权）：登录页上线后，
# 只提 X-Token 会让人以为 Bearer 不可用。error 字段与整体结构未动，
# 前端只读 error，不解析 hint。
UNAUTHORIZED_BODY = {
    "error": "unauthorized",
    "hint": "非本机访问需带 Authorization: Bearer 会话令牌（或 X-Token 旧令牌）请求头",
}

# 没有账号时给用户的指引。503 响应与启动日志用**同一句**。
NO_ACCOUNT_MESSAGE = "尚未设置账号：请先运行 python manage.py set-password 创建口令"

# 必须是 RLock：create_session / validate_session / revoke_* 都会在持锁状态下
# 再调用 save_sessions（它自己也要加锁），用普通 Lock 会自锁死。
_write_lock = threading.RLock()


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_iso(s):
    try:
        dt = datetime.datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _atomic_write(path: Path, text: str) -> None:
    """原子写：先写 .tmp 再 os.replace（与 hub/writer.py 的 _atomic_write 同款）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- 账号
def load_account() -> dict:
    """读 account.json；损坏或不存在时返回空 dict（视作"没有账号"）。"""
    if not ACCOUNT_JSON.exists():
        return {}
    try:
        data = json.loads(ACCOUNT_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_account(acct: dict) -> None:
    with _write_lock:
        _atomic_write(ACCOUNT_JSON, json.dumps(acct, ensure_ascii=False, indent=2))


def account_exists() -> bool:
    return bool((load_account().get("password_hash") or "").strip())


def set_password(username: str, password: str, revoke_sessions: bool = True) -> dict:
    """写账号。**只存哈希**，绝不落明文口令。

    revoke_sessions=True 时撤销该账号的全部会话（改口令 / CLI --reset 的语义）。
    """
    old = load_account()
    now = _now().isoformat()
    acct = {
        "username": username,
        "password_hash": _HASHER.hash(password),
        "created_at": old.get("created_at") or now,
        "updated_at": now,
    }
    save_account(acct)
    if revoke_sessions:
        revoke_all_sessions()
    return acct


def verify_password(password: str) -> bool:
    """校验口令是否匹配当前账号。账号不存在时走等价运算并返回 False。"""
    stored = (load_account().get("password_hash") or "").strip()
    if not stored:
        _dummy_verify(password)
        return False
    try:
        _HASHER.verify(stored, password)
        return True
    except Exception:
        return False


def check_login(username: str, password: str) -> bool:
    """登录校验：口令错与用户名错返回同一个 False，耗时也一致。

    无论用户名对不对都先跑一遍 Argon2，避免用响应时间区分二者。
    """
    acct = load_account()
    stored = (acct.get("password_hash") or "").strip()
    if not stored:
        _dummy_verify(password)
        return False
    ok = False
    try:
        _HASHER.verify(stored, password)
        ok = True
    except Exception:
        ok = False
    return ok and username == (acct.get("username") or "")


# ---------------------------------------------------------------- 会话
def token_hash(token: str) -> str:
    """会话令牌的存储形式。服务端**不存明文令牌**。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _user_agent_digest(user_agent: str) -> str:
    """只存 UA 摘要，不存原文（UA 属于可识别信息）。"""
    return "sha256:" + hashlib.sha256((user_agent or "").encode("utf-8")).hexdigest()[:16]


def load_sessions() -> list:
    if not SESSIONS_JSON.exists():
        return []
    try:
        data = json.loads(SESSIONS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_sessions(sessions: list) -> None:
    with _write_lock:
        _atomic_write(SESSIONS_JSON, json.dumps(sessions, ensure_ascii=False, indent=2))


def _is_expired(rec: dict, now=None) -> bool:
    """过期判定：绝对上限 OR 滑动 TTL，两者都要（缺一不可）。"""
    now = now or _now()
    abs_exp = _parse_iso(rec.get("absolute_expires_at"))
    if abs_exp is None or now >= abs_exp:
        return True
    last = _parse_iso(rec.get("last_seen_at"))
    if last is None:
        return True
    return (now - last).total_seconds() > SLIDING_TTL_SECONDS


def create_session(user_agent: str = "", username: str = "") -> tuple:
    """新建会话，返回 (明文令牌, 记录)。明文令牌只在这里出现一次。"""
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    now = _now()
    rec = {
        "token_hash": token_hash(token),
        "username": username,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "absolute_expires_at": (now + datetime.timedelta(seconds=ABSOLUTE_TTL_SECONDS)).isoformat(),
        "user_agent": _user_agent_digest(user_agent),
    }
    with _write_lock:
        sessions = [s for s in load_sessions() if not (isinstance(s, dict) and _is_expired(s, now))]
        sessions.append(rec)
        save_sessions(sessions)
    return token, rec


def validate_session(token: str):
    """校验会话令牌。有效返回记录（并滑动 last_seen_at），无效返回 None。

    副作用：清掉过期会话（不积累）、在滑动窗口需要时刷新 last_seen_at。
    """
    if not token:
        return None
    th = token_hash(token)
    now = _now()
    with _write_lock:
        raw = load_sessions()
        kept = []
        found = None
        dirty = False
        for rec in raw:
            if not isinstance(rec, dict):
                dirty = True
                continue
            expired = _is_expired(rec, now)
            if rec.get("token_hash") == th:
                if expired:
                    dirty = True          # 命中的那条已过期，直接丢弃
                    continue
                last = _parse_iso(rec.get("last_seen_at"))
                if last is None or (now - last).total_seconds() >= SESSION_TOUCH_INTERVAL:
                    rec = dict(rec)
                    rec["last_seen_at"] = now.isoformat()
                    dirty = True
                found = rec
                kept.append(rec)
                continue
            if expired:
                dirty = True
                continue
            kept.append(rec)
        if dirty:
            save_sessions(kept)
    return found


def revoke_session(token: str) -> bool:
    """撤销单个会话（logout）。"""
    if not token:
        return False
    th = token_hash(token)
    with _write_lock:
        raw = load_sessions()
        kept = [r for r in raw if not (isinstance(r, dict) and r.get("token_hash") == th)]
        if len(kept) != len(raw):
            save_sessions(kept)
            return True
    return False


def revoke_all_sessions() -> int:
    """撤销全部会话（改口令 / CLI --reset）。返回被撤销的条数。"""
    with _write_lock:
        raw = load_sessions()
        if raw:
            save_sessions([])
        return len(raw)


def session_expires_at(rec: dict) -> str:
    """会话的当前有效期 = min(滑动到期, 绝对到期)。"""
    last = _parse_iso(rec.get("last_seen_at")) or _now()
    idle = last + datetime.timedelta(seconds=SLIDING_TTL_SECONDS)
    absolute = _parse_iso(rec.get("absolute_expires_at")) or idle
    return min(idle, absolute).isoformat()


# ---------------------------------------------------------------- 请求侧
def session_token_from_request(request) -> str:
    """从**请求头**取会话令牌。**绝不读 query**——会话令牌只走头。

    认两种写法：
      Authorization: Bearer <session>
      X-Token: <session>
    （X-Token 同时也是旧共享令牌的载体；旧令牌不匹配任何会话，校验自然失败。）
    """
    auth = request.headers.get("authorization") or ""
    if auth[:7].lower() == "bearer ":
        tok = auth[7:].strip()
        if tok:
            return tok
    h = request.headers.get("x-token") or request.headers.get("X-Token")
    return (h or "").strip()


def unauthorized_response():
    """返回与 legacy 完全一致的 401 响应体（逐字节相同）。"""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=401, content=UNAUTHORIZED_BODY)
