"""routers/ 拆分回归测试（M1b-2）。

锁三件事：
1. **注册顺序**：main.py 自己的 35 条路由必须是 EXPECTED_OWN 这个确切序列
   （拆分前后唯一允许的差异是"同一域聚到一起"，这里把最终顺序固化下来）；
2. **静态页顺序敏感对**：/hub 必须早于 /hub/{path:path}、/app 必须早于 /app/{path:path}；
3. **静态处理器真的被命中**：/hub、/app 返回的是页面本体而不是被通配规则吃掉，
   /hub/{path}、/app/{path} 仍能取到资源。
"""
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from dump_routes import dump  # noqa: E402

# 拆分后 main.py 自有路由 + 10 个域的期望注册顺序。
# 与拆分前 73 条相比，唯一变化是"同一域聚在一起"。
#
# 关于 ("GET", "/")：它读 LAN_IP/SERVER_PORT 全局，owner 要求"本轮不动"，
# 因此连它在 main.py 里的位置也不动——装饰器还在 include 块之后，
# 于是它落在全部路由的最末尾（第 73 条）。见 test_root_route_is_last。
EXPECTED_OWN = [
    ("GET", "/api/auth/token"),
    # auth（M2a 身份端点；routers/auth.py，紧跟在 main.py 自带的 /api/auth/token 之后）
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    ("PUT", "/api/auth/password"),
    # static_pages
    ("GET", "/hub"),
    ("GET", "/server.js"),
    ("GET", "/hub/{path:path}"),
    ("GET", "/app"),
    ("GET", "/app/{path:path}"),
    # tasks
    ("GET", "/api/tasks"),
    ("POST", "/api/tasks/add"),
    ("POST", "/api/tasks/patch"),
    # legacy_life（Gate 0 §0.5 待删）
    ("POST", "/api/health"),
    ("GET", "/api/health"),
    # docs
    ("POST", "/api/daily-report"),
    ("GET", "/api/daily-report"),
    ("GET", "/api/doc"),
    ("PUT", "/api/doc"),
    ("GET", "/api/diary"),
    ("PUT", "/api/diary"),
    ("GET", "/api/deeptutor/notes"),
    ("GET", "/api/deeptutor"),
    # favorites（含 summary）
    ("GET", "/api/favorites"),
    ("GET", "/api/summary"),
    # usage
    ("GET", "/api/usage"),
    ("POST", "/api/usage"),
    # pomodoro
    ("POST", "/api/pomodoro"),
    ("GET", "/api/pomodoro"),
    # settings
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    # media
    ("GET", "/img/{path:path}"),
    ("POST", "/api/photo/upload"),
    ("GET", "/api/photos"),
    ("GET", "/photos/{month}/{name}"),
    # M2c-P3：媒体签名下发（把规范化路径换成 ?sig=&exp= 的短时签名 URL）
    ("POST", "/api/media/sign"),
    # ai
    ("POST", "/api/ai/chat"),
    ("GET", "/api/ai/context"),
]


@pytest.fixture(scope="module")
def all_routes():
    import main

    return dump(main.app)


def test_own_routes_exact_order(all_routes):
    """前 4 条是 FastAPI 内置（openapi/docs/redoc），之后必须紧跟 EXPECTED_OWN。"""
    builtins = all_routes[:4]
    assert [p for _, p in builtins] == [
        "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
    ], f"FastAPI 内置路由顺序变了: {builtins}"

    own = all_routes[4:4 + len(EXPECTED_OWN)]
    assert own == EXPECTED_OWN, _diff(own, EXPECTED_OWN)


def test_router_blocks_come_after_own(all_routes):
    """hub / health / openmaic 与根路由 / 排在自有路由之后。"""
    own = all_routes[4:4 + len(EXPECTED_OWN)]
    rest = all_routes[4 + len(EXPECTED_OWN):]
    assert rest, "hub/health/openmaic 路由不该消失"
    for p in (p for _, p in rest):
        assert p == "/" or p.startswith("/api/hub/") or p.startswith("/health/"), (
            f"多出未知路由: {p}"
        )


def test_root_route_is_last(all_routes):
    """/ 读 LAN_IP/SERVER_PORT 全局，owner 要求本轮不动，故它仍在 main.py 末尾，
    注册顺序上落在全部路由最后。"""
    assert all_routes[-1] == ("GET", "/"), f"末条应为 GET /，实际 {all_routes[-1]}"
    assert sum(1 for _, p in all_routes if p == "/") == 1


def test_total_route_count(all_routes):
    """基线 73 条（M1b-2 拆分后）
    → M2a 加 4 个身份端点 = 77
    → M2c-P3 加 1 个媒体签名端点 = 78

    任何增删路由都会走到这里。如果是故意改的，请同步更新本断言与 EXPECTED_OWN。
    """
    assert len(all_routes) == 78, (
        f"路由条数变了: {len(all_routes)}（期望 78 = 基线 73 + M2a 的 4 个身份端点 "
        f"+ M2c-P3 的 1 个媒体签名端点）。"
        f"新增/删除路由都会走到这里，如果是故意改的，请同步更新本断言与 EXPECTED_OWN。"
    )


# ---------------- 静态页顺序与行为 ----------------

def test_static_route_order_inside_router():
    from routers import static_pages

    paths = [r.path for r in static_pages.router.routes]
    assert paths.index("/hub") < paths.index("/hub/{path:path}")
    assert paths.index("/app") < paths.index("/app/{path:path}")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import main

    return TestClient(main.app, client=("127.0.0.1", 51234))


def test_hub_hits_page_not_wildcard(client):
    """/hub 必须返回 hub.html 本体（若被 /hub/{path} 吃掉会 404 或返回别的东西）。"""
    r = client.get("/hub")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert body.lstrip().startswith("<!DOCTYPE"), "不是 HTML 页面"
    assert "hub.html" not in r.url.path


def test_app_hits_index_not_wildcard(client):
    r = client.get("/app")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.text.lstrip().startswith("<!DOCTYPE"), "不是 SPA 入口"


def test_wildcard_still_serves_assets(client):
    """/hub/{path} 与 /app/{path} 仍能取到真实资源。"""
    from routers import static_pages

    # 旧页公共模块（经 /server.js 与 /hub/server.js 两条路都应可达）
    r1 = client.get("/server.js")
    assert r1.status_code == 200, r1.text
    assert "javascript" in r1.headers["content-type"]

    r2 = client.get("/hub/server.js")
    assert r2.status_code == 200, r2.text

    # SPA 的一个真实 asset（未构建时跳过，不让测试依赖构建产物）
    assets = static_pages.APP_DIST / "assets"
    if assets.is_dir():
        js = sorted(assets.glob("*.js"))
        if js:
            name = js[0].name
            r3 = client.get(f"/app/assets/{name}")
            assert r3.status_code == 200, r3.text
            assert "javascript" in r3.headers["content-type"]


def test_wildcard_missing_file_returns_its_own_404(client):
    """通配规则对不存在的文件返回"文件不存在"，证明它仍在工作。"""
    r = client.get("/hub/definitely-not-here.js")
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "文件不存在"

    r2 = client.get("/app/definitely-not-here.js")
    assert r2.status_code == 404, r2.text
    assert r2.json()["detail"] == "文件不存在"


def test_no_router_imports_main():
    """硬约束：routers 里不许 import main（会成环）。"""
    import ast

    routers_dir = SERVER_DIR / "routers"
    for f in sorted(routers_dir.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "main":
                pytest.fail(f"{f.name} import 了 main，违反 routers → main 禁入约定")
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] != "main", f"{f.name} import 了 main"


# ---------------- 辅助 ----------------

def _diff(got, want):
    lines = ["路由序列不一致："]
    for i, (g, w) in enumerate(zip(got, want)):
        mark = " " if g == w else "×"
        lines.append(f"  {mark} {i:2d} got={g[0]} {g[1]!r}  want={w[0]} {w[1]!r}")
    if len(got) != len(want):
        lines.append(f"  长度不同: got={len(got)} want={len(want)}")
    return "\n".join(lines)
