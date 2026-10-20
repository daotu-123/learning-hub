# -*- coding: utf-8 -*-
"""M1c: /api/v1 兼容别名（路径改写中间件）。

对外收敛到 /api/v1，但**旧路径必须继续可用**：已发布的 APK 还在打旧路径，
同时它又通过热更新拿到新 bundle——两条必须同时活着，覆盖一个版本周期。

做法选 A（路径改写），不选 B（路由级别名）：
    改写发生在中间件层，`app.routes` 一条都不新增（仍是 73 条），
    新旧路径命中的是**同一个端点函数、同一份响应**，不存在"两套路由漂移"。
    B 要给每个 router 再挂一套前缀，会动 router 定义与注册顺序，
    风险更高，且新增端点时极易漏挂一套。

改写规则（刻意从严，不做任何"猜"）：
    - 只改写前缀**恰好**是 "/api/v1/" 的路径；
    - "/api/v1"（无尾斜杠）不改写——交给路由层按原样 404，不替调用方猜意图；
    - "/api/v10/xxx" 不改写（不是 "/api/v1/" 前缀）；
    - /health/*、/hub、/app、/、/img/*、/photos/* 等非 "/api/v1/" 路径一律不碰；
    - query string / 请求头 / body / HTTP 方法原样透传；
    - 响应不经任何包装，状态码 / content-type / body 一个字节都不动。

================================================================================
中间件嵌套顺序（实测，不是推断）
================================================================================
Starlette 的 `add_middleware()` 是往 `app.user_middleware` 的**头部**插，
而 `build_middleware_stack()` 里 `user_middleware[0]` 是**最外层**。
所以「后注册 = 更外层 = 更早执行」。本 app 的注册顺序与最终调用链是：

    注册顺序（源码从上到下）              最终调用链（从外到内）
    ---------------------------------     -------------------------------------
    1. CORSMiddleware                     1. ServerErrorMiddleware
    2. @app.middleware  allow_private_network   2. ApiV1AliasMiddleware   ← 本模块
    3. @app.middleware  auth_guard        3. auth_guard
    4. install() 本模块                   4. allow_private_network
                                          5. CORSMiddleware
                                          6. router

改写层必须在 auth_guard **外面**（也就是比它**晚**注册）。原因很实在：
auth_guard 用 `request.url.path` 判断放行，读的是
AUTH_EXEMPT_API = {"/api/hub/netinfo", "/api/auth/token"}。
若改写晚于鉴权，auth_guard 看到的是 "/api/v1/auth/token"——不在白名单里，
非回环请求一律 401，等于把令牌下发端点直接打死。

放在 CORS / PNA 外面也没问题，已逐条确认：
    - CORSMiddleware 只看 Origin / 方法 / 头，不看 path，改写位置对它无影响；
    - PNA 兜底中间件只看 `access-control-request-private-network` 请求头，
      同样与 path 无关；它仍在内层，预检响应照旧会被补上该头；
    - 静态页与 FileResponse 不受影响：这些路径本就不匹配 "/api/v1/" 前缀。

为什么用纯 ASGI 中间件而不是 `@app.middleware("http")`：
    后者是 BaseHTTPMiddleware，响应要经 anyio 内存流中转一层。本服务有大量
    FileResponse（/app/*、/img/*、照片），再套一层纯属浪费；纯 ASGI 只复制
    并修改 scope 字典，零缓冲。

已知且刻意保留的差异（不算 bug，见 README「/api/v1 约定」）：
    带尾斜杠的请求 `/api/v1/tasks/` 会被改写成 `/api/tasks/`，再由 Starlette
    的 redirect_slashes 307 到 `/api/tasks`。指向目标不含 v1 前缀，但**能正常
    访问**（旧路径就是别名），因此不改写 Location 响应头——那属于改响应内容，
    不在"路径改写"的职责范围内。
"""
import re

# 唯一被改写的目标前缀。注意结尾的斜杠是故意的：
# "/api/v1" 不匹配（无尾斜杠 → 404，不猜），"/api/v10/" 也不匹配。
API_V1_PREFIX = "/api/v1/"
LEGACY_PREFIX = "/api/"

_PREFIX_BYTES = API_V1_PREFIX.encode("ascii")
_LEGACY_BYTES = LEGACY_PREFIX.encode("ascii")

# 只用于把 "/api/v1/" 之外的部分原样拼回去；不做 any 归一化。
_REWRITE = re.compile(r"^/api/v1/(?P<rest>.*)$", re.DOTALL)


def rewrite_path(path: str):
    """返回改写后的路径；不需要改写时返回 None。

    这是纯函数，测试可以直接调，不必起服务。
    """
    if not isinstance(path, str) or not path.startswith(API_V1_PREFIX):
        return None
    m = _REWRITE.match(path)
    if m is None:  # pragma: no cover - startswith 已保证能匹配
        return None
    return LEGACY_PREFIX + m.group("rest")


class ApiV1AliasMiddleware:
    """ASGI 中间件：`/api/v1/<rest>` → `/api/<rest>`，交给现有路由处理。

    只处理 `scope["type"] == "http"`；lifespan / websocket 原样透传。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            new_path = rewrite_path(scope.get("path") or "")
            if new_path is not None:
                # 复制一份 scope：不改上游（外层中间件 / ServerErrorMiddleware)持有的 dict
                scope = dict(scope)
                scope["path"] = new_path
                raw = scope.get("raw_path")
                if isinstance(raw, (bytes, bytearray)) and raw.startswith(_PREFIX_BYTES):
                    # 保留 rest 部分的 percent-encoding，只换前缀
                    scope["raw_path"] = _LEGACY_BYTES + bytes(raw[len(_PREFIX_BYTES):])
                else:
                    scope["raw_path"] = new_path.encode("utf-8")
        await self.app(scope, receive, send)


def install(app):
    """注册为**最外层**中间件。

    必须在本 app 的其它中间件**之后**调用——`add_middleware` 往头部插，
    头部即最外层。放在 auth_guard 之前注册会让改写晚于鉴权，
    `/api/v1/auth/token` 与 `/api/v1/hub/netinfo` 会直接 401。
    这条顺序由 tests/test_apiv1.py::test_alias_runs_before_auth 锁死。
    """
    app.add_middleware(ApiV1AliasMiddleware)
    return app
