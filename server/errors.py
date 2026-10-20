# -*- coding: utf-8 -*-
"""统一错误响应（M1a-C）。

形状（新增的规范错误体）：
    {"error": {"code": "...", "message": "..."}}

**兼容策略：只新增，不改名不删除。**
既有端点的 HTTPException / 参数校验错误原本返回 `{"detail": ...}`，前端有三处仍在读它：
    web/src/api/server.ts:75      data.detail
    web/src/hub/hubStore.ts:197   (await r.json()).detail
    web/src/hub/hubStore.ts:571   j.detail || JSON.stringify(j)
因此处理器在返回新形状的同时**原样保留 detail 字段**。删掉它会让三处错误提示
退化成 "HTTP 400"，属于用户可见的行为回归——这正是本轮禁止的。

401 例外：鉴权中间件直接返回 JSONResponse（不走 HTTPException），
其 `{"error":"unauthorized","hint":...}` 完全不受本模块影响，形状一个字不变。
"""
import json

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# 状态码 → 机器可读错误码。未列出的状态码统一用 http_error。
CODE_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
    504: "gateway_timeout",
}


def code_for(status: int) -> str:
    return CODE_BY_STATUS.get(status, "http_error")


def _message(detail) -> str:
    """detail 可能是 str / list / dict，统一转成可读字符串。"""
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(detail)


async def http_exception_handler(request, exc: StarletteHTTPException):
    """HTTPException → 新形状 + 保留 detail。"""
    payload = {"error": {"code": code_for(exc.status_code), "message": _message(exc.detail)}}
    if exc.detail is not None:
        payload["detail"] = exc.detail          # 兼容：前端仍在读
    return JSONResponse(
        status_code=exc.status_code,
        content=payload,
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(request, exc: RequestValidationError):
    """请求体/查询参数校验失败（422）→ 新形状 + 保留 detail（原为 pydantic 错误列表）。"""
    errors = jsonable_encoder(exc.errors())
    parts = []
    for e in errors:
        loc = [str(x) for x in e.get("loc", []) if x != "body"]
        where = ".".join(loc) or "body"
        parts.append(f"{where}: {e.get('msg', '')}".strip())
    return JSONResponse(
        status_code=422,
        content={
            "error": {"code": "validation_error", "message": "; ".join(parts) or "请求参数校验失败"},
            "detail": errors,                    # 兼容：原样保留错误列表
        },
    )


async def unhandled_exception_handler(request, exc: Exception):
    """未捕获异常 → 500。原行为是纯文本 Internal Server Error，这里升级为 JSON。

    不写 exc 详情到响应体（避免把内部路径/堆栈泄给客户端）；明细由
    ServerErrorMiddleware 照常抛给 uvicorn 的 error logger。
    """
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "服务器内部错误"}},
    )


def register(app) -> None:
    """把三个处理器挂到 FastAPI app 上。"""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
