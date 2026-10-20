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
