"""健康检查端点测试（M1a-B）。

锁定三点：
1. `/health/live`、`/health/ready` **免鉴权**（非回环来源也不要令牌）；
2. 依赖可用时 ready 200，data 目录不可写 / usage.db 不可读时 503 且带 checks 明细；
3. ready 的 503 走 JSONResponse 而非 HTTPException，形状不被统一错误处理器改写。
"""
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_TOKEN

LAN = ("192.168.1.50", 51234)      # 模拟同网段设备（非回环）
LOOP = ("127.0.0.1", 51234)


@pytest.fixture(scope="module")
def client():
    from main import app

    # 非回环来源：验证"不带令牌也能过"
    return TestClient(app, client=LAN)


def test_live_ok_without_token(client):
    r = client.get("/health/live")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok"}


def test_ready_ok_in_test_env(client):
    """测试环境下 data 目录可写、usage.db 可读或尚未建库 → 200。"""
    r = client.get("/health/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"data_dir", "usage_db"}
    assert all(c["ok"] for c in body["checks"].values()), body


def test_ready_fails_when_usage_db_unreadable(client, monkeypatch):
    import health

    # 指向一个非 SQLite 文件：只读打开会直接失败
    monkeypatch.setattr(health, "USAGE_DB", health.Path("E:/agent/androd-app/server/data/settings.json"))
    r = client.get("/health/ready")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["status"] == "fail"
    assert body["checks"]["usage_db"]["ok"] is False
    assert "error" in body["checks"]["usage_db"]


def test_ready_fails_when_data_dir_not_writable(client, monkeypatch, tmp_path):
    import health

    blocker = tmp_path / "not-a-dir.txt"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(health, "DATA_DIR", blocker)     # 探针文件建不进去
    r = client.get("/health/ready")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["status"] == "fail"
    assert body["checks"]["data_dir"]["ok"] is False


def test_ready_shape_is_not_rewritten_by_error_handler(client):
    """503 必须保留 status/checks 两个字段（不能被统一错误形状包走）。"""
    r = client.get("/health/ready")
    body = r.json()
    assert "error" not in body, "ready 的响应不该被统一错误处理器改写"
    assert "status" in body and "checks" in body


def test_health_endpoints_are_not_under_api_prefix():
    """防呆：万一以后有人把 /health 挪到 /api/ 下面，鉴权就会开始拦它。

    注意用 openapi() 而不是 app.routes：本版本 FastAPI 的 include_router 生成的是
    `_IncludedRouter` 包装对象，直接遍历 app.routes 看不到子路由。
    """
    from main import app

    paths = set(app.openapi()["paths"].keys())
    assert "/health/live" in paths
    assert "/health/ready" in paths
    # 业务健康模块（睡眠/运动）在 /api/health，与探针是两回事，不许混
    assert "/api/health" in paths
    assert not any(p.startswith("/api/health/") for p in paths)


def test_loopback_also_allowed():
    from main import app

    c = TestClient(app, client=LOOP)
    assert c.get("/health/live").status_code == 200
    assert c.get("/health/ready").status_code == 200


def test_ready_with_token_from_lan(client):
    """带令牌时行为不变（令牌不该让 ready 变形状）。"""
    r = client.get("/health/ready", headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
