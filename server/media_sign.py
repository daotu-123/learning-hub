# -*- coding: utf-8 -*-
"""M2c-P3：短时签名 URL（HMAC-SHA256）。

## 要解决的问题

`/img/*`、`/photos/*` 不以 `/api/` 开头，而 `auth_guard` 只校验 `/api/`
（静态页面必须放行，否则页面本身都打不开）。于是局域网任意设备
`GET /photos/2026-08/xxx.jpg` 就能拿到你的照片——这是**真实漏洞**，不是理论风险。

## 为什么照片不用 Blob（M2b 壁纸那套）

壁纸只有一张，fetch + Blob 完全可行（M2b 已实测通过）。
照片不一样：

1. **数量**：`/api/photos` 一次能返回 200 张。走 Blob 意味着先把 200 张全部
   下载成 ArrayBuffer 再渲染，`loading="lazy"` 直接失效，首屏内存不可控。
2. **日记图片不是受控 src**：Obsidian 里的 `![[图片.png]]` 是**用户正文**，
   前端拿不到、也不该去改写它的引用方式。Blob 方案要求每处引用点都改写成
   受控组件，这等于要求 owner 重写日记语法——不可接受。

签名 URL 让 `<img src="...">` 保持原样，浏览器原生懒加载、缓存、
右键另存全都继续工作。

## 签名内容与安全边界

    sig = HMAC-SHA256(secret, f"{path}\n{exp}")[0:32] 的 base64url（无 padding）

- **绑定 path**：把 A 图片的签名改到 B 图片上会验签失败。
- **绑定 exp**：过期即失效，签发新签名不需要任何服务端状态。
- **URL 里绝不出现会话令牌**：只有 `sig` 与 `exp`，两者都不是凭据明文。
  `sig` 已被 `logging_setup` 的脱敏正则覆盖（`token|sig` 都在内），
  所以访问日志里落地的是 `sig=***`。
- **默认有效期 5 分钟**（`HUB_MEDIA_URL_TTL`，上限强制 300s，
  不给"配成一天"留口子——照片不是机密，但它是隐私，5 分钟足够渲染完）。
- secret 落 `server/data/media_url_secret`（`0o600`）。
  首次调用时惰性生成，用 `secrets.token_bytes(32)`。

## 为什么必须 `secrets.compare_digest`

签名比较是逐字节的字符串比较。用 `==` 比较 HMAC 输出，
理论上存在时序侧信道（通过响应时间推断正确前缀）。
Python 的 `==` 对定长字符串会短路，`compare_digest` 不会。

## 已知限制（诚实记录）

签名 URL **不能撤销**：在有效期内，拿到 URL 的人都能看。
对本项目（照片是 owner 自己的）这个风险可接受；
若将来要放给别人用，得改成服务端查表校验，那就等于回到 Blob 方案。
"""

import base64
import hashlib
import hmac
import secrets
import time
from pathlib import Path
from typing import Optional

from config import DATA_DIR

SECRET_FILE = DATA_DIR / "media_url_secret"

# 硬上限：即使有人把环境变量配成一天，也不生效。
MAX_TTL_SECONDS = 300
DEFAULT_TTL_SECONDS = 300

_cache: Optional[bytes] = None


def get_secret() -> bytes:
    """取签名密钥；不存在则惰性生成。

    生成时机刻意放在**首次签发**而不是服务启动：
    启动时生成会让"从没签过名的部署"也在磁盘上多一个秘密文件。
    """
    global _cache
    if _cache is not None:
        return _cache
    try:
        if SECRET_FILE.exists():
            raw = SECRET_FILE.read_bytes().strip()
            if len(raw) >= 32:
                _cache = raw
                return _cache
    except OSError:
        pass
    sec = secrets.token_bytes(32)
    try:
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        SECRET_FILE.write_bytes(sec)
        try:
            SECRET_FILE.chmod(0o600)
        except OSError:
            pass        # Windows 上 chmod 语义有限，失败不致命
    except OSError:
        # 落盘失败 → 本次运行内仍可用（内存里的 secret），只是重启后旧签名全失效。
        # 这比直接抛异常让整个服务起不来要好。
        pass
    _cache = sec
    return sec


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sign(path: str, expires_at: int, secret: Optional[bytes] = None) -> str:
    """对 path + exp 生成签名。"""
    sec = secret or get_secret()
    msg = ("%s\n%d" % (path, int(expires_at))).encode("utf-8")
    return _b64(hmac.new(sec, msg, hashlib.sha256).digest())


def verify(path: str, expires_at: int, sig: str, secret: Optional[bytes] = None) -> bool:
    """校验签名与有效期。**任何一项不过都返回 False，不区分原因。**"""
    if not sig or not expires_at:
        return False
    try:
        exp = int(expires_at)
    except (TypeError, ValueError):
        return False
    if exp <= int(time.time()):
        return False
    expect = sign(path, exp, secret)
    return hmac.compare_digest(expect, str(sig))


def signed(path: str, ttl: Optional[int] = None, base: str = "") -> dict:
    """生成可直接放进 <img src> 的 URL。

    返回 {"url": ..., "expires_at": ...}。
    """
    exp = int(time.time()) + int(ttl or DEFAULT_TTL_SECONDS)
    # TTL 强制夹在 (0, MAX] —— 环境变量配错也拦得住
    if exp - int(time.time()) > MAX_TTL_SECONDS:
        exp = int(time.time()) + MAX_TTL_SECONDS
    # base 是服务器根（如 "http://10.0.0.5:8637"），拼成 <base><path>?sig=&exp=
    return {
        "url": "%s%s?sig=%s&exp=%d" % (base, _with_sep(path), sign(path, exp), exp),
        "expires_at": exp,
    }


def _with_sep(path: str) -> str:
    if not path.startswith("/"):
        return "/" + path
    return path
