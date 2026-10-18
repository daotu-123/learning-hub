"""APK 侧跨域与 Private Network Access 回归测试。

APK 内网页源是 http://appassets.androidplatform.net（私有网络地址），
访问 LAN 上的 http://192.168.x.x:8637 时，Chrome 会先发 PNA 预检。
若 CORSMiddleware 未开 allow_private_network，Starlette 会直接返回
400 Disallowed CORS private-network，App 侧所有请求全挂。
"""
import pytest
from fastapi.testclient import TestClient

ORIGIN = "http://appassets.androidplatform.net"


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
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-private-network") == "true"
    assert r.headers.get("access-control-allow-origin") in ("*", ORIGIN)


def test_plain_preflight_allowed(client):
    r = client.options(
        "/api/hub/webversion",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") in ("*", ORIGIN)


def test_actual_request_has_cors_header(client):
    r = client.get("/api/hub/webversion", headers={"Origin": ORIGIN})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") in ("*", ORIGIN)
