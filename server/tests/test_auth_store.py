# -*- coding: utf-8 -*-
"""身份存储层回归测试（M2a 第一步：账号 + 会话 + CLI）。

只测**存储与校验**这一层，不碰 HTTP。端点与双轨在 test_auth_endpoints.py。

纪律：断言里不能直接写 `assert SECRET not in text`——pytest 失败时会把 SECRET
的值展开打印出来，等于把口令/令牌写进了 CI 日志。统一走 conftest.leaks()：
它返回布尔值，pytest 只会显示 `assert not leaks(...)`，不会展开参数。
"""
import json

import auth_sessions
from auth_sessions import (
    ABSOLUTE_TTL_SECONDS,
    MIN_PASSWORD_LENGTH,
    SLIDING_TTL_SECONDS,
)
from conftest import leaks

# 测试夹具用的假口令。不是任何真实凭据。
PW = "unit-test-only-not-a-real-secret"
NEW_PW = "unit-test-only-not-a-real-secret-2"
WRONG_PW = "unit-test-only-wrong-password"


def _make_account(store, username="tester", password=PW):
    auth_sessions.set_password(username, password)
    return username


# ================================================================ A 账号

def test_account_file_stores_hash_only(store):
    """account.json 里绝不能出现明文口令。"""
    _make_account(store)
    raw = (store / "account.json").read_text(encoding="utf-8")
    assert not leaks(raw, PW), "account.json 里有明文口令"
    acct = json.loads(raw)
    assert acct["username"] == "tester"
    assert acct["password_hash"].startswith("$argon2id$")
    assert "created_at" in acct and "updated_at" in acct


def test_password_hash_is_salted_and_unique(store):
    """同一口令两次哈希必须不同（Argon2id 自带随机盐）。"""
    a = auth_sessions.set_password("tester", PW)["password_hash"]
    b = auth_sessions.set_password("tester", PW)["password_hash"]
    assert a != b


def test_verify_password(store):
    _make_account(store)
    assert auth_sessions.verify_password(PW) is True
    assert auth_sessions.verify_password(WRONG_PW) is False


def test_verify_password_without_account_returns_false(store):
    """没有账号时也不能崩，且必须返回 False。"""
    assert auth_sessions.verify_password(PW) is False


def test_check_login_does_not_distinguish_username(store):
    """用户名错与口令错必须都返回 False（响应层再保证同一条消息）。"""
    _make_account(store, username="tester")
    assert auth_sessions.check_login("tester", PW) is True
    assert auth_sessions.check_login("tester", WRONG_PW) is False
    assert auth_sessions.check_login("nosuchuser", PW) is False
    assert auth_sessions.check_login("nosuchuser", WRONG_PW) is False


def test_account_exists(store):
    assert auth_sessions.account_exists() is False
    _make_account(store)
    assert auth_sessions.account_exists() is True


def test_set_password_preserves_created_at(store):
    first = auth_sessions.set_password("tester", PW)
    second = auth_sessions.set_password("tester", NEW_PW)
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]


# ================================================================ B 会话

def test_session_file_stores_hash_only(store):
    """sessions.json 只存令牌哈希，明文令牌一次都不许落盘。"""
    token, rec = auth_sessions.create_session(user_agent="pytest")
    raw = (store / "sessions.json").read_text(encoding="utf-8")
    assert not leaks(raw, token), "sessions.json 里有明文令牌"
    sess = json.loads(raw)
    assert len(sess) == 1
    assert sess[0]["token_hash"] == auth_sessions.token_hash(token)
    assert sess[0]["token_hash"] != token
    for field in ("created_at", "last_seen_at", "absolute_expires_at", "user_agent"):
        assert field in sess[0], "缺字段 %s" % field


def test_user_agent_stored_as_digest(store):
    _token, rec = auth_sessions.create_session(user_agent="Mozilla/5.0 SecretAgent")
    assert "SecretAgent" not in rec["user_agent"]
    assert rec["user_agent"].startswith("sha256:")


def test_validate_session_accepts_valid_token(store):
    token, _rec = auth_sessions.create_session()
    rec = auth_sessions.validate_session(token)
    assert rec is not None
    assert rec["token_hash"] == auth_sessions.token_hash(token)


def test_validate_session_rejects_forged_token(store):
    auth_sessions.create_session()
    assert auth_sessions.validate_session("forged-token-value") is None
    assert auth_sessions.validate_session("") is None
    assert auth_sessions.validate_session(None) is None


def test_expired_session_is_rejected_and_cleaned(store):
    """absolute_expires_at 已过的记录 → 校验失败，且从文件里清掉。"""
    token, rec = auth_sessions.create_session()
    sess = json.loads((store / "sessions.json").read_text(encoding="utf-8"))
    sess[0]["absolute_expires_at"] = "2000-01-01T00:00:00+00:00"
    (store / "sessions.json").write_text(json.dumps(sess), encoding="utf-8")

    assert auth_sessions.validate_session(token) is None
    after = json.loads((store / "sessions.json").read_text(encoding="utf-8"))
    assert after == [], "过期会话没有被清理"


def test_sliding_ttl_expires_after_idle(store):
    """滑动 TTL：last_seen_at 太久没更新 → 失效。"""
    token, rec = auth_sessions.create_session()
    sess = json.loads((store / "sessions.json").read_text(encoding="utf-8"))
    sess[0]["last_seen_at"] = "2000-01-01T00:00:00+00:00"
    (store / "sessions.json").write_text(json.dumps(sess), encoding="utf-8")
    assert auth_sessions.validate_session(token) is None


def test_absolute_cap_survives_active_use(store):
    """绝对上限 30 天：即使一直在用，created_at + 30 天后也必须失效。"""
    token, _rec = auth_sessions.create_session()
    sess = json.loads((store / "sessions.json").read_text(encoding="utf-8"))
    sess[0]["absolute_expires_at"] = "2000-01-01T00:00:00+00:00"
    sess[0]["last_seen_at"] = "2999-01-01T00:00:00+00:00"   # 假装刚用过
    (store / "sessions.json").write_text(json.dumps(sess), encoding="utf-8")
    assert auth_sessions.validate_session(token) is None


def test_ttl_constants():
    """两个 TTL 都必须在，且绝对上限严格大于滑动 TTL。"""
    assert SLIDING_TTL_SECONDS == 7 * 24 * 3600
    assert ABSOLUTE_TTL_SECONDS == 30 * 24 * 3600
    assert ABSOLUTE_TTL_SECONDS > SLIDING_TTL_SECONDS


def test_expired_sessions_do_not_accumulate(store):
    """每次读写都清理过期会话，文件里不积累。"""
    for _ in range(3):
        auth_sessions.create_session()
    sess = json.loads((store / "sessions.json").read_text(encoding="utf-8"))
    assert len(sess) == 3
    sess[0]["absolute_expires_at"] = "2000-01-01T00:00:00+00:00"
    (store / "sessions.json").write_text(json.dumps(sess), encoding="utf-8")
    auth_sessions.create_session()          # 触发清理
    after = json.loads((store / "sessions.json").read_text(encoding="utf-8"))
    assert len(after) == 3, "过期会话没被清理干净"


def test_revoke_session(store):
    token, _rec = auth_sessions.create_session()
    assert auth_sessions.revoke_session(token) is True
    assert auth_sessions.validate_session(token) is None


def test_revoke_all_sessions(store):
    auth_sessions.create_session()
    auth_sessions.create_session()
    assert auth_sessions.revoke_all_sessions() == 2
    assert auth_sessions.load_sessions() == []


# ================================================================ A CLI
# 注意：下面每条都带 --force-default-dir。M3-P0-3 加了「目标数据目录是
# 仓库内默认 server/data 就拦下」的防呆闸门，而这些用例只关心口令逻辑，
# 账号文件早已被 store 夹具重定向到临时目录（auth_sessions.ACCOUNT_JSON），
# DATA_DIR 却仍指向仓库默认值。加这个标志是明确告诉闸门"我知道落点，
# 这些用例测的不是防呆"——防呆自己的用例在 test_manage.py。

def test_cli_set_password_interactive(store, monkeypatch, capsys):
    """交互式输入两遍：一致才通过；输出里绝不能出现口令。"""
    import manage

    good = "cli-test-good-password"
    # 第 1 轮太短被拒；第 2 轮两次不一致被拒；第 3 轮一致才通过
    answers = iter([
        "too-short",
        good, good + "-typo",
        good, good,
    ])
    monkeypatch.setattr(manage, "_read_secret", lambda prompt="": next(answers))

    rc = manage.main(["set-password", "--username", "tester", "--force-default-dir"])
    assert rc == 0
    out = capsys.readouterr().out
    assert not leaks(out, good), "CLI 输出里出现了口令"

    acct = json.loads((store / "account.json").read_text(encoding="utf-8"))
    assert acct["username"] == "tester"
    assert acct["password_hash"].startswith("$argon2id$")
    assert not leaks(json.dumps(acct), good), "账号文件里有明文口令"


def test_cli_reads_from_stdin_when_not_a_tty(store, monkeypatch, capsys):
    """非交互（管道 / 重定向）时也要能用——Windows 的 getpass 会挂死。"""
    import io
    import sys as _sys

    import manage

    good = "cli-stdin-good-password"
    monkeypatch.setattr(_sys, "stdin", io.StringIO(good + "\n" + good + "\n"))
    rc = manage.main(["set-password", "--username", "tester", "--force-default-dir"])
    assert rc == 0
    acct = json.loads((store / "account.json").read_text(encoding="utf-8"))
    assert acct["password_hash"].startswith("$argon2id$")
    assert not leaks(json.dumps(acct), good), "账号文件里有明文口令"


def test_cli_refuses_existing_account_without_reset(store, monkeypatch, capsys):
    """已有账号时默认拒绝，必须显式 --reset。"""
    import manage

    _make_account(store)
    monkeypatch.setattr(manage, "_read_secret", lambda prompt="": NEW_PW)
    rc = manage.main(["set-password", "--force-default-dir"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "--reset" in out
    # 账号没被动过
    assert auth_sessions.verify_password(PW) is True


def test_cli_reset_overwrites_and_revokes_sessions(store, monkeypatch, capsys):
    """--reset 覆盖账号，并把该账号的全部会话撤销。"""
    import manage

    _make_account(store)
    token, _rec = auth_sessions.create_session(username="tester")
    assert auth_sessions.validate_session(token) is not None

    monkeypatch.setattr(manage, "_read_secret", lambda prompt="": NEW_PW)
    rc = manage.main(["set-password", "--reset", "--force-default-dir"])
    assert rc == 0
    out = capsys.readouterr().out
    assert not leaks(out, NEW_PW), "CLI 输出里出现了口令"
    assert auth_sessions.verify_password(NEW_PW) is True
    assert auth_sessions.verify_password(PW) is False
    assert auth_sessions.validate_session(token) is None, "--reset 没有撤销会话"


def test_cli_min_length(store, monkeypatch, capsys):
    """口令短于最小长度必须被拒。"""
    import manage

    short = "x" * (MIN_PASSWORD_LENGTH - 1)
    answers = iter([short, short, "x" * MIN_PASSWORD_LENGTH, "x" * MIN_PASSWORD_LENGTH])
    monkeypatch.setattr(manage, "_read_secret", lambda prompt="": next(answers))
    rc = manage.main(["set-password", "--force-default-dir"])
    assert rc == 0
    assert auth_sessions.account_exists() is True
    assert auth_sessions.verify_password("x" * MIN_PASSWORD_LENGTH) is True
