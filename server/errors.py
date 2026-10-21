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


# input 值脱敏上限。二进制内容整体替换，字符串超长才截断。
_MAX_INPUT_STR = 200


def _sanitize_value(v):
    """把任意值转成**保证可 JSON 序列化**的形式。

    顺序很重要：bytes/bytearray 必须在通用分支之前处理——
    jsonable_encoder 对 bytes 用 `bytes.decode()`，非 UTF-8 就会炸
    （本轮 bug 的直接触发点），这里改成不解释内容、只报大小。
    """
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "<binary %d bytes>" % len(bytes(v))
    if isinstance(v, str):
        return v if len(v) <= _MAX_INPUT_STR else v[:_MAX_INPUT_STR] + "…<已截断>"
    if isinstance(v, dict):
        return {str(k): _sanitize_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_sanitize_value(x) for x in v]
    # 其它类型（含 pydantic 的 ErrorWrapper、自定义对象）一律转 repr 再截断
    try:
        s = repr(v)
    except Exception:
        s = "<unrepresentable %s>" % type(v).__name__
    return s if len(s) <= _MAX_INPUT_STR else s[:_MAX_INPUT_STR] + "…<已截断>"


def _safe_error_item(e) -> dict:
    """单个 pydantic 错误项 → 保证可序列化。

    保留 loc / msg / type（前端与测试都按这几个字段读），
    其余键逐个脱敏。任何意外都退化成 {"msg": ...}，
    绝不让异常从错误处理器里逃出去（那会把 422 变成 500）。
    """
    try:
        if not isinstance(e, dict):
            return {"msg": _sanitize_value(e)}
        out = {}
        for k in ("loc", "msg", "type"):
            if k in e:
                out[k] = _sanitize_value(e[k])
        if "input" in e:
            out["input"] = _sanitize_value(e["input"])
        if "ctx" in e:
            out["ctx"] = _sanitize_value(e["ctx"])
        # url（pydantic v2 有时带）等其它键一并脱敏保留
        for k, v in e.items():
            if k not in out:
                out[k] = _sanitize_value(v)
        return out
    except Exception:
        return {"msg": "请求参数校验失败"}


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
    """请求体/查询参数校验失败（422）→ 新形状 + 保留 detail（原为 pydantic 错误列表）。

    **为什么不能直接用 jsonable_encoder(exc.errors())**（本轮修的坑）：
    pydantic 的错误项里带 `input` 字段，值是**触发校验失败的原始输入**。
    当客户端把非 JSON 内容打到要求 JSON 的接口上（例：往
    `/api/hub/wallpaper` 发 multipart），`input` 就是一段二进制字节。
    FastAPI 的 `jsonable_encoder` 对 bytes 的编码规则是 `bytes.decode()`，
    于是非 UTF-8 的二进制（PNG 的 `\x89PNG` 头）在这里抛
    `UnicodeDecodeError` —— 错误处理器自己崩了，422 变成 500，
    客户端拿到的还是"服务器内部错误"，完全看不出是自己请求格式不对。

    因此这里**不把 exc.errors() 整个交给 jsonable_encoder**，而是逐项
    手工构造保证可序列化的结构：
        - loc / msg / type 这类字段本来就是 str，原样保留
        - input 按类型脱敏：bytes/bytearray 换成 "<binary N bytes>"，
          超长字符串截断，其它类型转成 repr 后再截断
        - ctx 里的值同样逐个脱敏
    任何一步再抛异常，就退化成一条最小可用的错误项——
    **422 的状态码和标准形状是底线，不能因为 body 奇怪就变成 500**。
    """
    try:
        raw_errors = exc.errors()
    except Exception:
        raw_errors = []

    errors = [_safe_error_item(e) for e in raw_errors]
    parts = []
    for e in errors:
        loc = [str(x) for x in e.get("loc", []) if x != "body"]
        where = ".".join(loc) or "body"
        parts.append(f"{where}: {e.get('msg', '')}".strip())
    return JSONResponse(
        status_code=422,
        content={
            "error": {"code": "validation_error", "message": "; ".join(parts) or "请求参数校验失败"},
            "detail": errors,                    # 兼容：仍是错误列表，但保证可序列化
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
