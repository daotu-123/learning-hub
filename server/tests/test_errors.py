"""统一错误格式测试（M1a-C）。

核心约束：**只新增，不改既有字段**。
- 新形状 {"error":{"code","message"}} 必须出现在 4xx/5xx 上；
- 既有 `detail` 字段必须原样保留（前端三处仍在读）；
- 鉴权中间件的 `{"error":"unauthorized","hint":...}` 必须一字不变。
"""
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_TOKEN

LAN = ("192.168.1.50", 51234)
LOOP = ("127.0.0.1", 51234)


@pytest.fixture(scope="module")
def lan():
    from main import app

    return TestClient(app, client=LAN)


@pytest.fixture(scope="module")
def loop():
    from main import app

    return TestClient(app, client=LOOP)


# ---------------- 404 未知路径 ----------------

def test_unknown_path_404(lan):
    r = lan.get("/definitely-not-a-real-path")
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert body["detail"] == "Not Found"        # 既有字段保留


def test_unknown_api_path_still_401(lan):
    """/api/ 下的未知路径先被鉴权中间件拦下，形状必须保持原样。"""
    r = lan.get("/api/hub/not-a-real-endpoint")
    assert r.status_code == 401, r.text
    body = r.json()
    assert body == {
        "error": "unauthorized",
        "hint": "非本机访问需带 Authorization: Bearer 会话令牌（或 X-Token 旧令牌）请求头",
    }


def test_unauthorized_shape_untouched(lan):
    """承重断言：error 是字符串而不是 dict，且 hint 原样在。"""
    r = lan.get("/api/hub/webversion")
    assert r.status_code == 401
    body = r.json()
    assert isinstance(body["error"], str) and body["error"] == "unauthorized"
    assert body["hint"]
    assert "code" not in body and "message" not in body


def test_auth_token_forbidden_shape(lan):
    """/api/auth/token 非回环 → 403，走 HTTPException，因此有新形状 + 保留 detail。"""
    r = lan.get("/api/auth/token")
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["error"]["code"] == "forbidden"
    assert body["error"]["message"] == "仅本机可读取令牌"
    assert body["detail"] == "仅本机可读取令牌"


# ---------------- 422 参数校验 ----------------

def test_validation_422(lan):
    r = lan.post("/api/tasks/add", json={}, headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert "name" in body["error"]["message"]
    # 既有 detail 是 pydantic 错误列表，必须原样保留
    assert isinstance(body["detail"], list) and body["detail"]
    assert body["detail"][0]["loc"] == ["body", "name"]


def test_query_param_422(lan):
    """查询参数类型错（days=abc）同样走 422。"""
    r = lan.get("/api/hub/overview?days=abc", headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


# ---------------- 422：不可编码 body 不能变 500（M3-P0-2） ----------------

def test_wallpaper_multipart_body_is_422_not_500(lan):
    """**本轮主修复点**：把 multipart 打到要求 JSON 的壁纸接口。

    修复前：pydantic 错误项里的 input 是二进制字节，errors.py 调
    jsonable_encoder 时走 bytes.decode() → UnicodeDecodeError →
    错误处理器自己崩 → 422 变 500，客户端只看到"服务器内部错误"。
    """
    # 一段真正的 PNG 头（0x89 不是合法 UTF-8 起始字节）
    png_head = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = lan.post(
        "/api/hub/wallpaper",
        content=png_head,
        headers={"X-Token": TEST_TOKEN, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["detail"], list) and body["detail"]


def test_wallpaper_multipart_form_is_422(lan):
    """真实 multipart/form-data（curl -F 那种）同样 422，不 500。"""
    r = lan.post(
        "/api/hub/wallpaper",
        files={"file": ("w.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")},
        headers={"X-Token": TEST_TOKEN},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


def test_binary_input_is_masked_not_dumped(lan):
    """二进制 input 不能原样回显（既是体积问题也是泄密问题）。"""
    r = lan.post(
        "/api/hub/wallpaper",
        content=b"\x89PNG\r\n\x1a\n" + b"A" * 500,
        headers={"X-Token": TEST_TOKEN, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 422, r.text
    text = r.text
    assert "binary" in text and "bytes" in text, text[:300]
    # 原始字节一个都不该出现在响应里
    assert "\x89" not in text
    assert "A" * 100 not in text


def test_long_string_input_is_truncated(lan):
    """超长字符串 input 也要截断，不能把整个 body 回显回去。

    用查询参数触发（days=非数字），input 就是那串超长字符。
    刻意不用 /api/tasks/add：那个接口 name 合法时会真的去写 vault 文件，
    测试会变成"往磁盘写 5000 个 x"，那不是本测试想验的东西。
    """
    r = lan.get("/api/hub/overview?days=" + "x" * 5000, headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 422, r.text
    assert len(r.text) < 5000, "input 没被截断，整个 5000 字符回显了"
    assert "已截断" in r.text


def test_sanitize_value_handles_weird_types():
    """_sanitize_value 对各种类型的兜底（直接单测，不绕 HTTP）。"""
    from errors import _MAX_INPUT_STR, _sanitize_value

    assert _sanitize_value(b"\x89PNG\xff\xfe") == "<binary 6 bytes>"
    assert _sanitize_value(bytearray(b"ab")) == "<binary 2 bytes>"
    assert _sanitize_value(None) is None
    assert _sanitize_value(True) is True
    assert _sanitize_value(3) == 3
    assert _sanitize_value("ok") == "ok"
    assert len(_sanitize_value("x" * 5000)) <= _MAX_INPUT_STR + 20
    assert _sanitize_value({"a": b"z"}) == {"a": "<binary 1 bytes>"}
    assert _sanitize_value([1, b"z"]) == [1, "<binary 1 bytes>"]

    class Weird:
        def __repr__(self):
            raise RuntimeError("no repr")

    assert isinstance(_sanitize_value(Weird()), str)


def test_safe_error_item_never_raises():
    """_safe_error_item 对任何输入都不许抛异常（否则 422 又变 500）。"""
    from errors import _safe_error_item

    assert _safe_error_item({"loc": ("body",), "msg": "x", "input": b"\xff"})["input"] == "<binary 1 bytes>"
    # 非 dict 输入：转成 repr 放进 msg，同样是"不抛异常"而非特定文案
    assert _safe_error_item("not a dict")["msg"] == "not a dict"
    assert isinstance(_safe_error_item(object()).get("msg"), str)
    assert _safe_error_item({}) == {}
    # 字段值本身会炸的情况（repr 抛异常的对象）
    class NoRepr:
        def __repr__(self):
            raise RuntimeError("boom")
    out = _safe_error_item({"loc": NoRepr(), "msg": NoRepr(), "input": NoRepr()})
    assert set(out) >= {"loc", "msg", "input"}


# ---------------- 400 业务校验 ----------------

def test_bad_request_400_keeps_detail(lan):
    r = lan.put(
        "/api/hub/settings",
        json={"accent": "zzz"},
        headers={"X-Token": TEST_TOKEN},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error"]["code"] == "bad_request"
    assert body["error"]["message"] == "accent 必须是 #RRGGBB"
    assert body["detail"] == "accent 必须是 #RRGGBB"   # 前端就读这个


def test_wallpaper_bad_path_400(lan):
    r = lan.get("/api/hub/wallpapers/..%2F..%2Fsettings.json", headers={"X-Token": TEST_TOKEN})
    assert r.status_code in (400, 404), r.text
    if r.status_code == 400:
        assert r.json()["error"]["code"] == "bad_request"


# ---------------- 405 ----------------

def test_method_not_allowed_405(loop):
    r = loop.delete("/api/hub/settings")
    assert r.status_code == 405, r.text
    assert r.json()["error"]["code"] == "method_not_allowed"


# ---------------- 500 ----------------

def test_internal_error_500(loop, monkeypatch):
    """未捕获异常 → 500 新形状。用 monkeypatch 让一个已注册路由真抛异常。"""
    import hub.router as hr

    monkeypatch.setattr(hr, "find_tailscale_ip", lambda: None)
    monkeypatch.setattr(hr, "find_lan_ip", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    # raise_server_exceptions=False：让 500 走异常处理器而不是在测试里炸出来
    client = TestClient(loop.app, client=LOOP, raise_server_exceptions=False)
    r = client.get("/api/hub/netinfo")
    assert r.status_code == 500, r.text
    body = r.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "服务器内部错误"
    assert "boom" not in r.text, "堆栈细节不该回给客户端"


# ---------------- 成功响应不受影响 ----------------

def test_success_response_unchanged(loop):
    r = loop.get("/api/hub/settings")
    assert r.status_code == 200
    body = r.json()
    assert "error" not in body and "detail" not in body
    assert body["wallpaper"] and body["accent"]
