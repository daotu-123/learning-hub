# -*- coding: utf-8 -*-
"""身份端点与双轨鉴权回归测试（M2a 第二步）。

覆盖：
  C 端点：login / logout / me / password；失败不区分"用户不存在"与"口令错"
  D 双轨：旧共享令牌继续有效，会话令牌只认请求头，401 逐字节不变
  v1 别名：/api/v1/auth/* 由 M1c 的改写中间件自动覆盖
  E 卫生：口令与令牌绝不出现在日志、断言消息里

纪律：断言里不能直接写 `assert SECRET not in text`——pytest 失败时会把 SECRET
的值展开打印出来，等于把口令/令牌写进了 CI 日志。统一走 conftest.leaks()。
"""
import json

import pytest
from fastapi.testclient import TestClient

import auth_sessions
from auth_sessions import MIN_PASSWORD_LENGTH, NO_ACCOUNT_MESSAGE, UNAUTHORIZED_BODY
from conftest import LAN, LOOP, TEST_TOKEN, leaks

# M2b 起更新的 401 响应体，逐字节照抄。
# 这是 owner 授权的唯一一次响应字节变化（只改 hint 文案，error 与结构未动）。
LEGACY_401_TEXT = (
    '{"error":"unauthorized","hint":"非本机访问需带 Authorization: Bearer 会话令牌（或 X-Token 旧令牌）请求头"}'
)

# 测试夹具用的假口令/假令牌。不是任何真实凭据。
PW = "unit-test-only-not-a-real-secret"
NEW_PW = "unit-test-only-not-a-real-secret-2"
WRONG_PW = "unit-test-only-wrong-password"


@pytest.fixture(scope="module")
def app():
    from main import app as _app

    return _app


@pytest.fixture
def lan_client(app):
    return TestClient(app, client=LAN)


@pytest.fixture
def loop_client(app):
    return TestClient(app, client=LOOP)


def _make_account(store, username="tester", password=PW):
    auth_sessions.set_password(username, password)
    return username


def _login(client, username="tester", password=PW):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ================================================================ C 端点

def test_login_without_account_returns_503(store, lan_client):
    """没有账号 → 503 + 明确指引；服务本身照常运行。"""
    r = lan_client.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert r.status_code == 503, r.text
    body = r.json()
    assert "manage.py" in body["detail"]
    assert body["detail"] == NO_ACCOUNT_MESSAGE


def test_service_still_serves_without_account(store, lan_client):
    """没有账号时其它端点照常工作（只是需要令牌）。"""
    assert lan_client.get("/health/live").status_code == 200
    assert lan_client.get("/api/hub/settings", headers={"X-Token": TEST_TOKEN}).status_code == 200


def test_login_success(store, lan_client):
    _make_account(store)
    r = lan_client.post("/api/auth/login", json={"username": "tester", "password": PW})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"token", "expires_at", "username"}
    assert body["username"] == "tester"
    assert isinstance(body["token"], str) and len(body["token"]) >= 32
    assert isinstance(body["expires_at"], str)


def test_login_failure_same_message_for_wrong_user_and_wrong_password(store, lan_client):
    """用户不存在与口令错 → 同一状态码、同一条消息。"""
    _make_account(store)
    r1 = lan_client.post("/api/auth/login", json={"username": "tester", "password": WRONG_PW})
    r2 = lan_client.post("/api/auth/login", json={"username": "nosuchuser", "password": PW})
    assert r1.status_code == r2.status_code == 401
    assert r1.content == r2.content, "两种失败的响应体不一致"
    assert r1.json()["detail"] == r2.json()["detail"]


def test_login_response_never_echoes_password(store, lan_client):
    _make_account(store)
    r = lan_client.post("/api/auth/login", json={"username": "tester", "password": PW})
    assert not leaks(r.text, PW), "登录响应里出现了口令"


def test_me_with_session(store, lan_client):
    _make_account(store)
    token = _login(lan_client)
    r = lan_client.get("/api/auth/me", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"username", "created_at", "expires_at"}
    assert body["username"] == "tester"


def test_me_with_x_token_header_session(store, lan_client):
    """X-Token 头也能携带会话令牌。"""
    _make_account(store)
    token = _login(lan_client)
    r = lan_client.get("/api/auth/me", headers={"X-Token": token})
    assert r.status_code == 200, r.text


def test_me_without_session_401_legacy_shape(store, lan_client):
    """没带会话 → 401，响应体与 legacy 逐字节一致。"""
    _make_account(store)
    r = lan_client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.content == LEGACY_401_TEXT.encode("utf-8"), "401 响应体变了"
    assert r.text == LEGACY_401_TEXT


def test_me_with_shared_token_401(store, lan_client):
    """旧共享令牌不是会话 → /me 必须 401（owner 定的边界）。"""
    _make_account(store)
    r = lan_client.get("/api/auth/me", headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 401
    assert r.content == LEGACY_401_TEXT.encode("utf-8")


def test_me_from_loopback_without_session_401(store, loop_client):
    """回环豁免只放行"页面能打开"，不代表能拿账号信息。"""
    _make_account(store)
    r = loop_client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.content == LEGACY_401_TEXT.encode("utf-8")


def test_logout_revokes_session(store, lan_client):
    _make_account(store)
    token = _login(lan_client)
    headers = {"Authorization": "Bearer " + token}
    assert lan_client.get("/api/auth/me", headers=headers).status_code == 200
    r = lan_client.post("/api/auth/logout", headers=headers)
    assert r.status_code == 200, r.text
    assert lan_client.get("/api/auth/me", headers=headers).status_code == 401


def test_logout_without_session_401(store, lan_client):
    _make_account(store)
    r = lan_client.post("/api/auth/logout")
    assert r.status_code == 401
    assert r.content == LEGACY_401_TEXT.encode("utf-8")


def test_change_password_revokes_all_old_sessions(store, lan_client):
    """改口令 → 旧会话全部失效，并返回一个新会话（本轮决定）。"""
    _make_account(store)
    token = _login(lan_client)
    other, _rec = auth_sessions.create_session(username="tester")
    headers = {"Authorization": "Bearer " + token}

    r = lan_client.put(
        "/api/auth/password",
        json={"old_password": PW, "new_password": NEW_PW},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"token", "expires_at", "username"}

    # 旧会话全部失效
    assert lan_client.get("/api/auth/me", headers=headers).status_code == 401
    assert lan_client.get(
        "/api/auth/me", headers={"Authorization": "Bearer " + other}
    ).status_code == 401

    # 新口令可登录
    r2 = lan_client.post("/api/auth/login", json={"username": "tester", "password": NEW_PW})
    assert r2.status_code == 200, r2.text
    # 旧口令不可用
    r3 = lan_client.post("/api/auth/login", json={"username": "tester", "password": PW})
    assert r3.status_code == 401

    # 返回的新会话可用
    assert lan_client.get(
        "/api/auth/me", headers={"Authorization": "Bearer " + body["token"]}
    ).status_code == 200


def test_change_password_with_wrong_old_password_401(store, lan_client):
    _make_account(store)
    token = _login(lan_client)
    r = lan_client.put(
        "/api/auth/password",
        json={"old_password": WRONG_PW, "new_password": NEW_PW},
        headers={"Authorization": "Bearer " + token},
    )
    assert r.status_code == 401
    # 口令没被改
    assert auth_sessions.verify_password(PW) is True


def test_change_password_rejects_short_new_password(store, lan_client):
    _make_account(store)
    token = _login(lan_client)
    r = lan_client.put(
        "/api/auth/password",
        json={"old_password": PW, "new_password": "short"},
        headers={"Authorization": "Bearer " + token},
    )
    assert r.status_code == 400
    assert auth_sessions.verify_password(PW) is True


# ================================================================ D 双轨

def test_shared_token_still_works_via_header(store, lan_client):
    """第一轨：旧共享令牌 + X-Token 头，继续有效。"""
    r = lan_client.get("/api/hub/settings", headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 200, r.text


def test_shared_token_still_works_via_query(store, lan_client):
    """第一轨：旧共享令牌 + ?token= 参数，继续有效（<img>/<a> 设不了头）。"""
    r = lan_client.get("/api/hub/settings?token=" + TEST_TOKEN)
    assert r.status_code == 200, r.text


def test_session_token_works_via_bearer(store, lan_client):
    """第二轨：会话令牌 + Authorization: Bearer。"""
    _make_account(store)
    token = _login(lan_client)
    r = lan_client.get("/api/hub/settings", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 200, r.text


def test_session_token_works_via_x_token(store, lan_client):
    """第二轨：会话令牌 + X-Token 头。"""
    _make_account(store)
    token = _login(lan_client)
    r = lan_client.get("/api/hub/settings", headers={"X-Token": token})
    assert r.status_code == 200, r.text


def test_no_credential_401_byte_identical(store, lan_client):
    """什么凭据都不带 → 401，且与改动前**逐字节**一致。"""
    r = lan_client.get("/api/hub/settings")
    assert r.status_code == 401
    assert r.content == LEGACY_401_TEXT.encode("utf-8"), "401 响应体变了"
    assert r.text == LEGACY_401_TEXT
    # 与常量也必须一致（防止有人改了 UNAUTHORIZED_BODY）
    assert json.dumps(UNAUTHORIZED_BODY, ensure_ascii=False, separators=(",", ":")) == LEGACY_401_TEXT


def test_session_token_in_query_is_rejected(store, lan_client):
    """会话令牌走 query → 401（只认头）。"""
    _make_account(store)
    token = _login(lan_client)
    r = lan_client.get("/api/hub/settings?token=" + token)
    assert r.status_code == 401, "会话令牌竟然能从 query 生效"
    assert r.content == LEGACY_401_TEXT.encode("utf-8")


def test_expired_session_rejected_like_no_token(store, lan_client):
    """过期会话 → 401，与"没带令牌"同一形状，不泄露原因。"""
    _make_account(store)
    token = _login(lan_client)
    sess = json.loads((store / "sessions.json").read_text(encoding="utf-8"))
    sess[0]["absolute_expires_at"] = "2000-01-01T00:00:00+00:00"
    (store / "sessions.json").write_text(json.dumps(sess), encoding="utf-8")

    r = lan_client.get("/api/hub/settings", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 401
    assert r.content == LEGACY_401_TEXT.encode("utf-8")


def test_revoked_session_rejected_like_no_token(store, lan_client):
    """撤销后 → 401，同一形状。"""
    _make_account(store)
    token = _login(lan_client)
    auth_sessions.revoke_session(token)
    r = lan_client.get("/api/hub/settings", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 401
    assert r.content == LEGACY_401_TEXT.encode("utf-8")


def test_forged_session_rejected_like_no_token(store, lan_client):
    """伪造的会话令牌 → 401，同一形状。"""
    r = lan_client.get("/api/hub/settings", headers={"Authorization": "Bearer forged-value"})
    assert r.status_code == 401
    assert r.content == LEGACY_401_TEXT.encode("utf-8")


# ================================================================ v1 别名

def test_v1_alias_login_me_logout(store, lan_client):
    """/api/v1/auth/* 由 M1c 的改写中间件自动覆盖。"""
    _make_account(store)
    r = lan_client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": PW}
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    headers = {"Authorization": "Bearer " + token}

    r2 = lan_client.get("/api/v1/auth/me", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["username"] == "tester"

    r3 = lan_client.post("/api/v1/auth/logout", headers=headers)
    assert r3.status_code == 200, r3.text
    assert lan_client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_v1_alias_password_change(store, lan_client):
    _make_account(store)
    token = _login(lan_client)
    r = lan_client.put(
        "/api/v1/auth/password",
        json={"old_password": PW, "new_password": NEW_PW},
        headers={"Authorization": "Bearer " + token},
    )
    assert r.status_code == 200, r.text
    assert auth_sessions.verify_password(NEW_PW) is True


# ================================================================ E 卫生

def test_login_is_exempt_from_auth(store, lan_client):
    """登录端点必须在豁免清单里，否则手机端根本登不进来。"""
    from main import AUTH_EXEMPT_API

    assert "/api/auth/login" in AUTH_EXEMPT_API
    r = lan_client.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert r.status_code != 401, "登录端点被鉴权挡住了"


def test_query_token_is_masked_in_logs():
    """会话令牌若被塞进 query，落盘前必须打码。"""
    from logging_setup import mask_query

    masked = mask_query("http://h/api/hub/settings?token=abcdef123456")
    assert "abcdef123456" not in masked
    assert "token=***" in masked


def test_no_account_message_mentions_cli():
    """指引必须明确告诉用户去建账号。"""
    assert "manage.py" in NO_ACCOUNT_MESSAGE
    assert "set-password" in NO_ACCOUNT_MESSAGE


def test_startup_prints_account_hint(store, monkeypatch, capsys):
    """没有账号时启动日志要打一行指引（服务照常启动）。"""
    import routers.favorites as fav

    monkeypatch.setattr(fav, "load_index_on_start", lambda: None)
    monkeypatch.setattr(fav, "background_refresh", lambda: None)

    import main

    main._startup()
    out = capsys.readouterr().out
    assert NO_ACCOUNT_MESSAGE in out


def test_startup_no_hint_when_account_exists(store, monkeypatch, capsys):
    import routers.favorites as fav

    monkeypatch.setattr(fav, "load_index_on_start", lambda: None)
    monkeypatch.setattr(fav, "background_refresh", lambda: None)
    _make_account(store)

    import main

    main._startup()
    out = capsys.readouterr().out
    assert NO_ACCOUNT_MESSAGE not in out
