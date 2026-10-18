"""APK 侧跨域与 Private Network Access 回归测试。

APK 内网页源是 http://appassets.androidplatform.net（私有网络地址），
访问 LAN 上的 http://192.168.x.x:8637 时，Chrome 会先发 PNA 预检。
若 CORSMiddleware 未开 allow_private_network，Starlette 会直接返回
400 Disallowed CORS private-network，App 侧所有请求全挂。

2026-10-18 起服务加了令牌鉴权（非回环必须带 X-Token），本文件的请求都要带上。
"""
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_TOKEN

ORIGIN = "http://appassets.androidplatform.net"
AUTH = {"X-Token": TEST_TOKEN}


@pytest.fixture(scope="module")
def client():
    from main import app

    return TestClient(app)


def test_pna_preflight_allowed(client):
    r = client.options(
        "/api/hub/webversion",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
            **AUTH,
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-private-network") == "true"
    assert r.headers.get("access-control-allow-origin") in ("*", ORIGIN)


def test_plain_preflight_allowed(client):
    r = client.options(
        "/api/hub/webversion",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET", **AUTH},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") in ("*", ORIGIN)


def test_actual_request_has_cors_header(client):
    r = client.get("/api/hub/webversion", headers={"Origin": ORIGIN, **AUTH})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") in ("*", ORIGIN)


# ---------------- CORS 白名单收紧回归（2026-10-18）----------------
# 原配置 allow_origins=["*"] 与「无鉴权 + 绑 0.0.0.0」叠加，等于数据全开放。
# 现改为白名单：APK 页面源 + 本机 + 私有网段 + Tailscale 100.64/10。

@pytest.mark.parametrize("origin", [
    "http://192.168.1.50:8637",
    "http://10.0.0.8:8637",
    "http://172.16.5.9:8637",
    "http://100.72.46.20:8637",      # Tailscale（手机常走这条）
    "http://127.0.0.1:8637",
    "http://localhost:8637",
])
def test_private_origins_allowed(client, origin):
    r = client.options(
        "/api/hub/webversion",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET", **AUTH},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize("origin", [
    "http://evil.example.com",
    "https://attacker.test",
])
def test_foreign_origin_not_echoed(client, origin):
    r = client.options(
        "/api/hub/webversion",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET", **AUTH},
    )
    echoed = r.headers.get("access-control-allow-origin")
    assert echoed not in (origin, "*"), f"不应回显外站 Origin，实际: {echoed}"
