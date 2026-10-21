# -*- coding: utf-8 -*-
"""M3-P0-1：usage.db 建表逻辑统一 + 首启（空数据目录）不再 500。

核心回归点：
    GET /api/summary 在**从未建过 usage 表**的数据目录下必须 200。
    修复前它抛 sqlite3.OperationalError: no such table: usage → 500，
    而只要先访问过一次 /api/usage 就又恢复 200（行为取决于请求顺序）。

测试刻意把 usage.db 指到临时目录，**绝不碰真实数据目录**。
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

import usage_db
from conftest import LAN, TEST_TOKEN
from main import app


@pytest.fixture
def fresh_usage_db(tmp_path, monkeypatch):
    """把 usage_db 的连接目标换成临时目录里的全新文件。

    返回临时库路径。**所有模块都经过 usage_db.connect()**，
    所以这里改一处就能让全部域指向同一个空库——这也是本次重构能测的前提：
    若各域还各自 sqlite3.connect(USAGE_DB)，monkeypatch 就得改五处。
    """
    db = tmp_path / "usage.db"
    monkeypatch.setattr(usage_db, "USAGE_DB", db)
    return db


# ============================================================ A. 模块本身
def test_schema_covers_all_four_tables(fresh_usage_db):
    con = usage_db.connect(fresh_usage_db)
    names = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"usage", "usage_hourly", "pomodoro", "health"} <= names, names


def test_connect_is_idempotent(fresh_usage_db):
    """重复调用不得报错（IF NOT EXISTS 语义），也不得破坏已有数据。"""
    con = usage_db.connect(fresh_usage_db)
    con.execute("INSERT INTO pomodoro(date, task, minutes, ts) VALUES('2026-01-01','x',25,'t')")
    con.commit()
    con.close()
    con = usage_db.connect(fresh_usage_db)
    usage_db.ensure_schema(con)          # 再来一次
    n = con.execute("SELECT COUNT(*) FROM pomodoro").fetchone()[0]
    con.close()
    assert n == 1


def test_connect_creates_missing_file(fresh_usage_db):
    assert not fresh_usage_db.exists()
    con = usage_db.connect(fresh_usage_db)
    con.close()
    assert fresh_usage_db.exists()


def test_default_path_is_config_usage_db():
    """不传参时必须走 config.USAGE_DB（生产路径不能被测试夹具污染）。"""
    import inspect
    from config import USAGE_DB as cfg
    src = inspect.getsource(usage_db.connect)
    assert "USAGE_DB" in src
    assert usage_db.USAGE_DB == cfg


# ============================================================ B. 空库上的各端点
def _client():
    return TestClient(app, client=LAN)


def test_summary_on_fresh_db_returns_200(fresh_usage_db):
    """**本轮主修复点**：空数据目录 + 第一次请求就是 /api/summary。"""
    r = _client().get("/api/summary", headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usage"] == {"apps": 0, "total_ms": 0}


def test_summary_does_not_depend_on_request_order(fresh_usage_db):
    """反过来也要成立：先 summary 再 usage，两边都 200（曾经的顺序依赖）。"""
    c = _client()
    a = c.get("/api/summary", headers={"X-Token": TEST_TOKEN})
    b = c.get("/api/usage?days=7", headers={"X-Token": TEST_TOKEN})
    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text


def test_pomodoro_endpoints_on_fresh_db(fresh_usage_db):
    c = _client()
    h = {"X-Token": TEST_TOKEN}
    assert c.get("/api/pomodoro", headers=h).status_code == 200
    assert c.post("/api/pomodoro", json={"date": "2026-01-01", "task": "t", "minutes": 25},
                  headers=h).status_code == 200


def test_hub_focus_endpoints_on_fresh_db(fresh_usage_db):
    """hub 域自己那份 pomodoro 读写，空库上同样必须可用。"""
    c = _client()
    h = {"X-Token": TEST_TOKEN}
    assert c.get("/api/hub/focus?days=1", headers=h).status_code == 200
    r = c.post("/api/hub/focus", json={"task": "t", "minutes": 25}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["saved"]["count"] >= 1


def test_legacy_health_endpoints_on_fresh_db(fresh_usage_db):
    c = _client()
    h = {"X-Token": TEST_TOKEN}
    assert c.get("/api/health", headers=h).status_code == 200


def test_all_four_tables_created_by_one_call(fresh_usage_db):
    """只调一次 connect()，四张表全在——这正是"抽成一处"要的。

    用 `>=` 而不是 `==`：`pomodoro` / `health` 带 AUTOINCREMENT，
    sqlite 会自动建一张 `sqlite_sequence` 内部表，那不是我们的业务表。
    """
    con = usage_db.connect(fresh_usage_db)
    con.close()
    con = sqlite3.connect(fresh_usage_db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"usage", "usage_hourly", "pomodoro", "health"} <= names, names


# ============================================================ C. 防回归：不许再散落建表
def _code_only(path) -> str:
    """剥掉注释与字符串字面量，只留代码。

    直接用正则扫原文会把文档字符串里提到的 "CREATE TABLE" 也算成违规
    （本轮写注释时就踩到过）。tokenize 是 Python 官方的词法切分，
    COMMENT 与 STRING 两类 token 丢掉即可。
    """
    import io
    import tokenize
    src = path.read_text(encoding="utf-8", errors="replace")
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except tokenize.TokenError:
        # 语法错误不该让本测试误报成"有散落建表"，直接抛给 import 测试去管
        return ""
    return " ".join(out)


def test_no_stray_create_table_in_callers():
    """调用点不得再写 CREATE TABLE——否则重构会慢慢腐化回去。

    允许的例外只有 usage_db.py 自己。这里用源码扫描而不是靠 review 自觉。
    """
    from pathlib import Path
    server = Path(__file__).resolve().parent.parent
    offenders = []
    for p in list(server.glob("*.py")) + list((server / "routers").glob("*.py")) + \
            list((server / "hub").glob("*.py")):
        if p.name == "usage_db.py" or p.name.startswith("test_"):
            continue
        if "CREATE" in _code_only(p) and "TABLE" in _code_only(p):
            offenders.append(p.name)
    assert not offenders, "这些文件里还有 CREATE TABLE，请改用 usage_db.connect(): %s" % offenders


def test_no_stray_sqlite3_connect_usage_db():
    """同样不许再裸连 USAGE_DB（会绕过 schema 保证）。

    白名单只有 health.py：它的 `/health/ready` 探针刻意以 **mode=ro 只读**
    打开，为的是"库坏了/没建"时如实报 503，而不是把库建出来骗过探针。
    那条路径不写任何数据，因此不受"必须先建表"约束。
    """
    from pathlib import Path
    server = Path(__file__).resolve().parent.parent
    offenders = []
    for sub in ("", "routers", "hub"):
        for p in (server / sub).glob("*.py") if sub else server.glob("*.py"):
            if p.name in ("usage_db.py", "health.py", "config.py") or p.name.startswith("test_"):
                continue
            code = _code_only(p)
            if "sqlite3" in code and "connect" in code and "USAGE_DB" in code:
                offenders.append(str(p.relative_to(server)))
    assert not offenders, "这些文件还在裸连 USAGE_DB: %s" % offenders