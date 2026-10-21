# -*- coding: utf-8 -*-
"""
Workbench PC Sync Server (工作台 PC 端同步服务器)
- 局域网内供 Android App 访问
- 聚合: 抖音/小红书当日收藏、DeepTutor 当日活动、Obsidian 日记读写、手机使用时间统计
- 所有数据只在本机 (E:\agent\androd-app\server\data\) 与 Obsidian vault 之间流动, 不上云

M1b-2 起本文件只保留：app 实例、三个中间件（CORS → PNA → auth）、鉴权代码、
GET /api/auth/token、GET /、include_router、启动入口。
业务路由按域拆到 routers/，共享工具在 common.py。
"""
import os
import time
import socket
import secrets
import threading
import datetime
import sys
from typing import Optional

# =====================================================================
#  M3-P0 编码安全：**必须在任何 print 之前**执行。
#  现象与理由见 stdiosafe.py 的模块注释（一处说明，main 与 manage 共用）。
# =====================================================================
from stdiosafe import force_utf8_stdio

force_utf8_stdio()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# M2a 身份体系：会话令牌校验 + legacy 401 响应体。
# UNAUTHORIZED_BODY 抽在 auth_sessions 里，是为了让这里的鉴权中间件与
# routers/auth.py 的会话校验共用**同一份** 401 响应体——两边各写一份迟早漂移，
# 而 401 的字节一变前端就可能退化。
from auth_sessions import (
    NO_ACCOUNT_MESSAGE,
    account_exists,
    session_token_from_request,
    unauthorized_response,
    validate_session,
)

# M2c-P1/P2：限流与客户端 IP 解析。
# clientip 不 import ratelimit，两者各自独立，方便测试单独构造实例。
from ratelimit import LIMITER, is_upload_path, retry_after
from clientip import is_loopback, request_client_ip
# 公网模式规则一律走 `publicmode.xxx()` 的**模块属性**调用，不 from-import。
# 原因：`from publicmode import local_bypass_enabled` 会把函数对象在导入期
# 绑死到本模块命名空间，测试 monkeypatch publicmode.local_bypass_enabled
# 之后 main 里的引用仍指向旧函数，公网模式测试会全部"通过但没测到东西"。
# 这不是洁癖：它让测试失去意义，而失去意义的绿灯比红灯更危险。
import publicmode
import media_sign

# 上面这 4 个（socket / time / sys / uvicorn）只在 `if __name__ == "__main__":` 块
# 及其派生的线程函数（UDP 广播 loop、_open_browser）里被用到。M1b-2 拆 routers 时
# 顶层 import 被一并清掉，结果是 `import main` 与 TestClient 全绿、而
# `python main.py`（start_hub.bat / PyInstaller 的真实入口）启动即 NameError。
# 顶层集中 import 是刻意的：写在 `__main__` 块里的 import 没有任何测试能覆盖到。
# 兜底的是 tests/test_startup_smoke.py（真跑一次 `python main.py`）。

# ---------------------------------------------------------------- paths
# M1a 配置化：路径/端口/令牌全部来自 config（环境变量驱动，缺省值 = 原硬编码）。
# M1b-2：settings 读写已下沉 common.py（auth_token 与 routers/settings 共用）。
from common import get_settings, save_settings
from config import DATA_DIR, HUB_AUTH_TOKEN, HUB_HOST, HUB_PORT, HUB_PUBLIC, UDP_PORT

DATA_DIR.mkdir(parents=True, exist_ok=True)

SERVER_PORT = HUB_PORT

# ---------------------------------------------------------------- 访问令牌
# 威胁模型（2026-10-18 审查）：服务绑 0.0.0.0:8637 且 CORS 全开、无鉴权，
# 同网段任意设备可直接读取日记/健康/照片，并可通过 PUT /api/hub/aiconfig
# 覆盖 DeepSeek Key。此外热更新通道 /api/hub/webfile 无鉴权 + 明文 HTTP，
# 改写一份 JS 即可拿到 window.Native 的全部原生能力。
#
# 策略：本机回环请求放行（桌面浏览器体验不变），非回环必须带令牌。
# 令牌来源优先级（M1a 起，既有顺序不变，仅在既有环境变量之后追加 HUB_AUTH_TOKEN）：
#   环境变量 WORKBENCH_AUTH_TOKEN > 环境变量 HUB_AUTH_TOKEN > settings.json > 首次自动生成并落盘。
# 客户端可用 X-Token 头，或用 ?token= 查询参数（<img>/<a> 无法设请求头）。
AUTH_TOKEN_ENV = "WORKBENCH_AUTH_TOKEN"

# 这些路径在任何情况下都不校验令牌：
#  - 静态页面/资源：不校验，否则页面本身都打不开
#  - /api/hub/netinfo：App 首次发现服务器地址时还不知道令牌
#  - /api/auth/token：仅回环可读，桌面端用它把令牌抄到手机上
#  - /api/auth/login：登录入口本身就是"还没有令牌"时调用的
AUTH_EXEMPT_API = {"/api/hub/netinfo", "/api/auth/token", "/api/auth/login"}

# M2c-P3：需要鉴权但**不以 /api/ 开头**的媒体前缀。
# 这三条历史上完全裸奔（auth_guard 只看 /api/），局域网任何设备都能读照片。
# 判定顺序刻意放在「回环豁免」**之后**：
#   桌面端本机预览照片/日记图片仍免令牌（回环豁免覆盖全部路径，含媒体）；
#   非回环则必须带凭据头（会话 Bearer / 旧 X-Token）或有效短时签名 URL。
MEDIA_PREFIXES = ("/img/", "/photos/", "/api/hub/wallpapers/")


def _loopback(host: str) -> bool:
    """判断请求是否来自本机。转调 clientip.is_loopback —— M2c 起登录限流
    也需要同一份判定，而从 routers 反向 import main 会成环。"""
    return is_loopback(host)


def _loopback_exempt(host: str) -> bool:
    """回环请求是否**豁免**鉴权/限流。

    与 `_loopback` 的区别就是 M3-P5 引入的那条：
    「来自回环」是事实，「回环该被豁免」是策略。公网模式下这两者必须分开——

        cloudflared / tailscale funnel 都是从**本机 127.0.0.1** 连进来的。

    所以公网模式一开，`127.0.0.1` 的来源不再自动等于「可信的本机」，
    必须由 `HUB_LOCAL_BYPASS=1` 显式声明"我确实要让本机免令牌"。
    没设 `HUB_PUBLIC` 时本函数恒等于 `_loopback`，行为逐字不变。
    """
    if not _loopback(host):
        return False
    return publicmode.local_bypass_enabled()


def auth_token() -> str:
    """读取（必要时生成）访问令牌。

    来源顺序（承重项，不许调整）：
      1) 环境变量 WORKBENCH_AUTH_TOKEN（既有）
      2) 环境变量 HUB_AUTH_TOKEN（M1a 新增，与 1 同级，插在既有 env 之后）
      3) settings.json 的 auth_token（既有）
      4) 都没有 → secrets.token_urlsafe(24) 生成并写回 settings.json（既有）
    """
    env = (os.environ.get(AUTH_TOKEN_ENV) or HUB_AUTH_TOKEN or "").strip()
    if env:
        return env
    s = get_settings()
    tok = (s.get("auth_token") or "").strip()
    if not tok:
        tok = secrets.token_urlsafe(24)
        save_settings({"auth_token": tok})
    return tok


def _request_token(request) -> str:
    """从请求里取令牌：优先 X-Token 头，其次 token 查询参数。"""
    h = request.headers.get("x-token") or request.headers.get("X-Token")
    if h:
        return h.strip()
    q = request.query_params.get("token")
    return (q or "").strip()


# ---------------------------------------------------------------- app
app = FastAPI(title="Workbench Sync Server", version="1.1.0")
# allow_private_network=True：APK 页面源是 http://appassets.androidplatform.net
# （私有网络地址），访问 LAN 的 http://192.168.x.x:8637 时 Chrome 会发
# Access-Control-Request-Private-Network 预检。Starlette 的 CORSMiddleware 默认
# 拒绝该预检（400 Disallowed CORS private-network），必须在此显式放行。
app.add_middleware(
    CORSMiddleware,
    # 2026-10-18 收紧：原来是 allow_origins=["*"]，配合「无鉴权 + 绑 0.0.0.0」
    # 等于把日记/健康/照片和 AI Key 完全暴露给同网段。现改为白名单：
    #   - APK 页面源 appassets.androidplatform.net
    #   - 本机、局域网私有网段、Tailscale 的 100.64.0.0/10
    # 真正的访问控制靠 X-Token 鉴权中间件，CORS 只是收敛面。
    allow_origins=[
        "http://appassets.androidplatform.net",
        "https://appassets.androidplatform.net",
    ],
    allow_origin_regex=(
        r"^https?://("
        r"localhost|127\.0\.0\.1|\[::1\]|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
        r"100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
        r")(?::\d+)?$"
    ),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)

@app.middleware("http")
async def allow_private_network(request, call_next):
    """兜底：给带 PNA 预检标记的响应补上 allow-private-network（老版本 Starlette 兼容）。"""
    resp = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


@app.get("/api/auth/token")
def auth_token_endpoint(request: Request):
    """把令牌交给本机（仅回环）。桌面浏览器用它显示，供手机端录入。"""
    host = request.client.host if request.client else ""
    if not _loopback(host):
        raise HTTPException(status_code=403, detail="仅本机可读取令牌")
    return {"token": auth_token()}


@app.middleware("http")
async def rate_limit_guard(request: Request, call_next):
    """M2c-P1：全局令牌桶 + 上传限频。**必须在 auth_guard 之内、路由之外**。

    放在 auth_guard 之后注册 → 位置更外层 → 先于鉴权执行，
    因此**未认证的扫描流量在碰 Argon2id 之前就被挡掉**。
    这正是限流该在的地方：爆破的每一发都要先过这一关。

    三条豁免（都与安全无关，是"限流会先杀死自己"的场景）：
        - 回环请求：本机桌面端，并发轮询不该被自己限死；
        - OPTIONS 预检：CORS 预检不带凭据，按 IP 限会给浏览器制造随机失败；
        - /api/auth/login：不走这里，走端点内更细的"按 (IP,账号)"退避。

    返回的 429 是**新状态码**，body 沿用 errors.py 的标准形状
    （{"error":{"code":"too_many_requests",...},"detail":...,"retry_after":N}）
    + Retry-After 头。401 的字面量一个字没动。
    """
    path = request.url.path
    if not path.startswith("/api/") and not path.startswith(MEDIA_PREFIXES):
        return await call_next(request)
    host = request.client.host if request.client else ""
    if _loopback_exempt(host):
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)

    ip = request_client_ip(request)
    delay = 0.0
    if is_upload_path(path):
        delay = LIMITER.upload_take(ip)
    else:
        delay = LIMITER.api_take(ip)
    if delay > 0:
        ra = retry_after(delay)
        # 429 的 body 刻意用 errors.py 的**标准形状**
        # {"error":{"code":"too_many_requests",...}}，而不是另起炉灶：
        # 项目里所有走 HTTPException 的 429 都会被 errors.py 归一化成这个形状，
        # 中间件若自己造一个 {"error":"rate_limited"}，前端就会同时面对两种
        # 429 body —— 那才是真正的坑。区分 429 与 401 用 **status_code**
        # 与 Retry-After，不靠 body。
        # detail 字段一并给上，与 errors.py 的兼容策略保持一致。
        return JSONResponse(
            status_code=429,
            content={
                "error": {"code": "too_many_requests", "message": "请求过于频繁，请稍后再试"},
                "detail": "请求过于频繁，请稍后再试",
                "retry_after": ra,
            },
            headers={"Retry-After": str(ra)},
        )
    return await call_next(request)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """非回环访问 /api/* 必须带令牌（双轨，M2a）。

    判定顺序（owner 2026-10-20 定）：
        1) 非 /api/ 路径（静态页面与资源）——不校验，否则页面本身打不开
           **M2c-P3 例外**：MEDIA_PREFIXES 里的媒体路径同样要校验
        2) 豁免清单 AUTH_EXEMPT_API（netinfo / auth/token / login）
        3) 回环豁免——本机桌面端体验不变
    2) 与 3) 都是"直接放行"，先后无所谓，这里按 owner 给的顺序写。

    双轨的意义：旧共享令牌必须继续有效，直到新版 APK 铺开（覆盖一个版本周期）。
    两套凭据互不干扰——会话令牌只认头，共享令牌还认 query。

    M2c-P3 新增第三轨：媒体短时签名（?sig=…&exp=…）。
    只对 MEDIA_PREFIXES 生效，且**放在凭据头之后**——
    带会话的请求本来就该走会话，没必要额外签发；签名只服务"无法带头的 <img>"。

    401 的响应体**与 legacy 逐字节一致**（auth_sessions.UNAUTHORIZED_BODY）——
    改一个字前端就可能退化，所以抽成常量由两处共用，从根上杜绝写法漂移。
    """
    path = request.url.path
    is_media = path.startswith(MEDIA_PREFIXES)
    if not path.startswith("/api/") and not is_media:
        return await call_next(request)
    host = request.client.host if request.client else ""
    if _loopback_exempt(host):
        return await call_next(request)
    if path in AUTH_EXEMPT_API:
        return await call_next(request)
    # 第一轨：旧共享令牌。X-Token 头优先，其次 ?token= 参数（<img>/<a> 无法设头）。
    expected = auth_token()
    given = _request_token(request)
    if expected and given and secrets.compare_digest(given, expected):
        return await call_next(request)
    # 第二轨：会话令牌。**只从请求头取**——会话令牌绝不走 query。
    session = session_token_from_request(request)
    if session and validate_session(session):
        return await call_next(request)
    # 第三轨（M2c-P3）：媒体短时签名。URL 里只有 sig + exp，**没有会话令牌**。
    if is_media:
        sig = request.query_params.get("sig")
        exp = request.query_params.get("exp")
        if media_sign.verify(path, exp, sig):
            return await call_next(request)
    return unauthorized_response()


# M2c-P4：安全响应头。注册在 auth_guard **之后** → 位置更外层 →
# 401 / 429 / 404 也都带着这几个头，而不是只有 200 才带。
# （若注册在 auth_guard 之前，鉴权失败会直接短路返回，浏览器就看不到 nosniff。）
from security_headers import ALWAYS_HEADERS, CSP_HEADER, should_send_csp


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """下发 Referrer-Policy / nosniff 等安全头；`/app` 额外下发 CSP 响应头。

    CSP 为何要写两处（meta + 响应头）见 security_headers.py 顶部注释——
    简单说：APK 页面不经过本服务器，只有 meta 能约束它；
    而 frame-ancestors 只有走响应头才生效。
    """
    resp = await call_next(request)
    for k, v in ALWAYS_HEADERS.items():
        resp.headers[k] = v
    if should_send_csp(request.url.path):
        resp.headers["Content-Security-Policy"] = CSP_HEADER
    return resp


# M1c：/api/v1 兼容别名（/api/v1/<rest> → /api/<rest>）。
# 位置是刻意的、也是唯一正确的：必须在 auth_guard **之后**注册。
# `add_middleware` 是往 user_middleware 头部插，头部 = 最外层 = 最先执行，
# 所以放这里才能让「改写」早于「鉴权」——否则 auth_guard 读到的是
# "/api/v1/auth/token"，不在 AUTH_EXEMPT_API 里，非回环一律 401。
# 顺序断言见 tests/test_apiv1.py::test_alias_runs_before_auth。
from apiv1 import install as install_api_v1_alias
install_api_v1_alias(app)

# 统一错误响应（M1a-C）：只新增 error 形状，保留既有 detail 字段
from errors import register as register_error_handlers
register_error_handlers(app)

# 日志配置（M1a-D）：access 日志的 token/sig 落盘前打码
from logging_setup import build_log_config, install_log_filters

# 覆盖 `uvicorn main:app` 启动：那种方式用 uvicorn 自己的默认 log_config，
# build_log_config 不参与，所以在 import 时就把过滤器挂到 logger 上。
# 同时挂 httpx logger：它自己会打 "HTTP Request: GET …?token=… " 这条出站日志。
install_log_filters()


# ---------------------------------------------------------------- 路由注册
# M1b-2 拆 routers/：按域 include，顺序即注册顺序。
# 既定顺序：static_pages → tasks → legacy_life → docs → favorites → usage →
#           pomodoro → settings → media → ai → hub → openmaic
# 尤其 /hub 要早于 /hub/{path:path}、/app 要早于 /app/{path:path}
# （两者都在 static_pages 内，文件内顺序已锁，见 tests/test_routers.py）。
# M2a 新增 auth 域，排在**最前**：让 /api/auth/token（main.py 自带）与
# /api/auth/{login,logout,me,password}（routers/auth.py）挨在一起。
from routers import auth, static_pages, tasks, legacy_life, docs, favorites
from routers import usage, pomodoro, settings, media, ai

for _r in (auth, static_pages, tasks, legacy_life, docs, favorites,
           usage, pomodoro, settings, media, ai):
    app.include_router(_r.router)

# Learning Hub 只读中枢（/api/hub/* + /hub 页面）
from hub.router import router as hub_router, find_tailscale_ip
app.include_router(hub_router)

# 健康检查（/health/live、/health/ready）——在 /api/ 之外，不进鉴权中间件
from health import router as health_router
app.include_router(health_router)

# Learning Hub: OpenMAIC AI 课堂（/api/hub/openmaic/*）
from hub.openmaic import router as openmaic_router
app.include_router(openmaic_router)


LAN_IP = None


@app.on_event("startup")
def _startup():
    """冷启动: 加载持久化索引 + 启动后台刷新线程（实现在 favorites 域）"""
    from routers.favorites import background_refresh, load_index_on_start

    # M3-P5：把公网模式的五项安全参数也打进日志。
    # 为什么要在这里再打一遍：`__main__` 块里的 print 只在 `python main.py`
    # 时执行，而**服务化部署走的是 uvicorn main:app**，那条路径一个 print 都
    # 看不到。排障时最需要知道的恰恰是"这机器上跑的到底是不是公网模式"，
    # 所以必须走 logging 进 server.log，两种启动方式都覆盖。
    _log_security_mode()

    load_index_on_start()
    t = threading.Thread(target=background_refresh, daemon=True)
    t.start()
    # M2a：没有账号时**服务照常启动**（否则本机与测试全崩），只是登录端点不可用。
    # 启动日志打一行与 503 响应完全相同的指引。
    if not account_exists():
        # flush=True：stdout 被重定向到文件时是块缓冲的，不 flush 这行会
        # 一直躺在缓冲区里，直到进程退出才落盘——而进程可能被杀。
        print("  " + NO_ACCOUNT_MESSAGE, flush=True)


def _log_security_mode():
    """把公网模式的安全参数打进 server.log（两种启动方式都覆盖）。"""
    import logging

    lg = logging.getLogger("hub.security")
    from clientip import TRUSTED

    lg.warning(
        "运行模式=%s 监听=%s:%s UDP广播=%s 回环免令牌豁免=%s 受信代理=%s 数据目录=%s",
        "公网" if HUB_PUBLIC else "本机/局域网",
        HUB_HOST, SERVER_PORT,
        "开" if publicmode.udp_discovery_enabled(HUB_PUBLIC) else "关",
        "开" if publicmode.local_bypass_enabled() else "关",
        ",".join(str(n) for n in TRUSTED.nets) or "(空)",
        DATA_DIR,
    )
    if HUB_PUBLIC and not TRUSTED:
        # 这两个组合起来是最容易出事的情形：公网模式 + 不采信任何代理头
        # → 限流把整个隧道当成一个 IP，一人用满额度全站被限。
        lg.warning(
            "⚠ 公网模式但 HUB_TRUSTED_PROXIES 为空：真实客户端 IP 取不到，"
            "限流会把整个隧道算作单一来源。隧道在本机时至少设 127.0.0.1。"
        )
    if HUB_PUBLIC and publicmode.local_bypass_enabled():
        lg.warning(
            "⚠ 公网模式 + 回环免令牌豁免已开：经隧道进来的流量（来源 127.0.0.1）"
            "同样免令牌，等于对公网开放无鉴权访问。"
        )


@app.get("/")
def root():
    return {
        "app": "workbench-sync-server", "version": "1.0.0",
        "now": datetime.datetime.now().isoformat(timespec="seconds"),
        "lan_ip": LAN_IP, "port": SERVER_PORT,
        "tailscale_ip": find_tailscale_ip(),
    }


# ---------------------------------------------------------------- main
def find_lan_ip() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def start_udp_broadcast(port: int, name: str) -> None:
    """局域网 UDP 广播服务存在性（手机 App 自动发现），协议: LEARNINGHUB|<name>|<port>"""

    def loop():
        msg = ("LEARNINGHUB|%s|%d" % (name, port)).encode("utf-8")
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(msg, ("255.255.255.255", UDP_PORT))
                s.close()
            except Exception:
                pass
            time.sleep(2)

    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    # M3-P5 公网模式硬闸：**必须在建任何目录、开任何端口之前**跑。
    # 放在这里而不是 _startup() 里，是因为 _startup() 是 FastAPI 的 startup
    # 事件，那时 uvicorn 已经绑好端口了——"拒绝启动"就变成了"先开门再关门"。
    _guard = publicmode.startup_public_guard()
    if _guard:
        sys.exit(_guard)

    LAN_IP = find_lan_ip()
    # UDP 广播：手机 App 自动发现（学习中枢 8637）。
    # 公网模式下关掉——广播是给同一广播域里的手机 App 用的，对外暴露时
    # 它只会告诉同网段所有设备"这里有个服务"，与目的相反。
    import platform
    _udp_on = publicmode.udp_discovery_enabled(HUB_PUBLIC)
    if _udp_on:
        start_udp_broadcast(SERVER_PORT, platform.node() or "PC")
    # 文件日志 (后台静默启动时无控制台, 排障依赖 server.log)
    # M1a-D：query 里的 token/sig 在落盘前打码（见 logging_setup 的说明）
    LOG_FILE = DATA_DIR / "server.log"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_CONFIG = build_log_config(LOG_FILE)
    print("=" * 60)
    print("  工作台同步服务器 v1.0.0")
    # M3-P5：模式相关五项（模式 / 绑定 / UDP / 回环豁免 / 受信代理）
    # 在公网模式下是**安全参数**，不打印就等于让人凭猜部署。
    print(f"  运行模式: {'公网模式（HUB_PUBLIC=1）' if HUB_PUBLIC else '本机/局域网模式'}")
    print(f"  监听地址: {HUB_HOST}:{SERVER_PORT}"
          + ("  ← 公网模式下 TLS 由隧道/反代终结" if HUB_PUBLIC else ""))
    print(f"  UDP 广播自动发现: {'开启' if _udp_on else '已关闭（公网模式）'}")
    _bypass = publicmode.local_bypass_enabled()
    if _bypass:
        print("  ⚠ 回环免令牌豁免: **已开启**（HUB_LOCAL_BYPASS=1）")
        print("     本机任何进程都可免令牌访问全部数据；"
              "公网模式下经隧道进来的流量也享受同一豁免。")
    else:
        print("  回环免令牌豁免: 已关闭（回环请求同样需要令牌）")
    from clientip import TRUSTED
    print("  受信代理列表: " + (", ".join(str(n) for n in TRUSTED.nets)
                                if TRUSTED else "（空 = 不采信任何代理头）"))
    if HUB_PUBLIC:
        print("-" * 60)
        print("  公网模式要点：")
        print("    · 需在隧道/反代侧设置受信代理，否则真实客户端 IP 取不到，")
        print("      限流会把整个隧道算成一个 IP。")
        print("    · 本机桌面端访问需要令牌（已登录的浏览器会自动带上会话）。")
    if not HUB_PUBLIC:
        print(f"  本机 IP: {LAN_IP}")
    ts_ip = find_tailscale_ip()
    if ts_ip:
        print(f"  Tailscale 远程地址: http://{ts_ip}:{SERVER_PORT}  (手机不连同一 WiFi 也能同步)")
    else:
        print("  Tailscale: 未检测到 (安装并登录后自动支持跨网络同步)")
    print(f"  数据目录: {DATA_DIR}")
    print(f"  日志文件: {LOG_FILE}")
    print(f"  手机 App 设置服务器地址为: http://<本机IP>:{SERVER_PORT}")
    print("=" * 60)

    # 端口已被占用（服务已在运行）→ 只打开网页，不重复启动（与 start_hub.bat 行为一致）
    def _port_busy(port: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            return False
        except OSError:
            return True
        finally:
            s.close()

    if _port_busy(SERVER_PORT):
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{SERVER_PORT}/hub")
        print("  服务已在运行，已为你打开网页。")
        sys.exit(0)

    # 后台线程：服务就绪后自动打开浏览器（打包为无窗口 exe 时这是唯一可见反馈）
    def _open_browser():
        import urllib.request
        import webbrowser
        for _ in range(40):
            time.sleep(0.5)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{SERVER_PORT}/", timeout=1)
                break
            except Exception:
                pass
        try:
            webbrowser.open(f"http://127.0.0.1:{SERVER_PORT}/hub")
        except Exception:
            pass

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host=HUB_HOST, port=SERVER_PORT, log_level="info", log_config=LOG_CONFIG)
