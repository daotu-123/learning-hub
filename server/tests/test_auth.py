"""访问令牌鉴权回归测试。

背景（2026-10-18 审查）：服务绑 0.0.0.0:8637，CORS 全开、无鉴权，
同网段任意设备可读取日记/健康/照片，并通过 PUT /api/hub/aiconfig 覆盖
DeepSeek Key；热更新通道 /api/hub/webfile 同样无鉴权 + 明文 HTTP。

修复后规则：
  - 非 /api/ 路径：不校验（静态页面要能打开）
  - AUTH_EXEMPT_API：/api/hub/netinfo（首次发现）、/api/auth/token（仅回环）
  - 回环请求：放行（桌面体验不变）
  - 其余：必须带 X-Token 头或 ?token= 参数
"""
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_TOKEN

LAN = ("192.168.1.50", 51234)      # 模拟同网段设备
LOOP = ("127.0.0.1", 51234)        # 模拟本机


@pytest.fixture(scope="module")
def app():
    from main import app as _app

    return _app


@pytest.fixture(scope="module")
def lan_client(app):
    return TestClient(app, client=LAN)


@pytest.fixture(scope="module")
def loop_client(app):
    return TestClient(app, client=LOOP)


# ---------------- 非回环必须带令牌 ----------------

def test_lan_without_token_rejected(lan_client):
    r = lan_client.get("/api/hub/webversion")
    assert r.status_code == 401, r.text
    assert r.json().get("error") == "unauthorized"


def test_lan_with_wrong_token_rejected(lan_client):
    r = lan_client.get("/api/hub/webversion", headers={"X-Token": "wrong-token"})
    assert r.status_code == 401


def test_lan_with_header_token_allowed(lan_client):
    r = lan_client.get("/api/hub/webversion", headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 200, r.text


def test_lan_with_query_token_allowed(lan_client):
    """<img>/<a> 无法设置请求头，必须支持 ?token= 形式。"""
    r = lan_client.get(f"/api/hub/webversion?token={TEST_TOKEN}")
    assert r.status_code == 200, r.text


# ---------------- 白名单与静态资源 ----------------

def test_netinfo_is_exempt(lan_client):
    """App 首次发现服务器时还不知道令牌，netinfo 必须免鉴权。"""
    r = lan_client.get("/api/hub/netinfo")
    assert r.status_code != 401, r.text


def test_static_page_not_blocked(lan_client):
    """静态页面不校验令牌，否则页面本身打不开。"""
    r = lan_client.get("/")
    assert r.status_code != 401, r.text


# ---------------- 回环放行 ----------------

def test_loopback_without_token_allowed(loop_client):
    r = loop_client.get("/api/hub/webversion")
    assert r.status_code == 200, r.text


# ---------------- 令牌下发端点 ----------------

def test_auth_token_only_from_loopback(loop_client, lan_client):
    r_loop = loop_client.get("/api/auth/token")
    assert r_loop.status_code == 200, r_loop.text
    assert r_loop.json().get("token") == TEST_TOKEN

    r_lan = lan_client.get("/api/auth/token")
    assert r_lan.status_code in (401, 403), r_lan.text
