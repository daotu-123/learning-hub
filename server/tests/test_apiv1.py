# -*- coding: utf-8 -*-
"""M1c: /api/v1 兼容别名回归测试。

验收口径（对应用户给的 1~4 条），全部用「同一份 app 实例、两个 Client」真打：

  1. 双路径矩阵：9 个端点各打旧路径与 /api/v1 路径，状态码 / content-type /
     JSON body 必须完全一致；
  2. 鉴权一致：非回环不带 token 的 401 响应体**逐字节**一致；带 token 200；
     回环豁免两条路径都成立；
  3. 豁免一致：/hub/netinfo、/auth/token 在两条路径上行为一致
     （auth/token 非回环仍 403，响应体逐字节一致）；
  4. 边界：/api/v1/no-such → 404 统一错误形状；/api/v1（无尾斜杠）→ 404。

另外锁两条结构性不变量：
  - 路由条数仍是 73，且没有任何一条路由带 /api/v1 前缀（证明是中间件方案，
    不是偷偷多挂了一套路由）；
  - 改写层在 auth_guard **外层**（这是 /api/v1/auth/token 不 401 的唯一原因）。

为什么矩阵要比 JSON 而不能只比状态码：状态码相同但 body 不同的情况下
（比如 v1 命中通配路由取了别的资源）只比状态码会漏掉。
为什么用结构比较而不是字节比较：个别端点会把当前时间写进 body
（例如 /api/hub/today 的生成时间），两次调用的字节不可能相同。
但**鉴权 401 / 403 的响应体是固定字符串，所以那几处用逐字节比较**。
"""
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_TOKEN

LAN = ("192.168.1.50", 51234)      # 模拟同网段设备（非回环）
LOOP = ("127.0.0.1", 51234)        # 模拟本机

API_V1 = "/api/v1"


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def app():
    from main import app as _app

    return _app


@pytest.fixture(scope="module")
def loop_client(app):
    return TestClient(app, client=LOOP)


@pytest.fixture(scope="module")
def lan_client(app):
    return TestClient(app, client=LAN)


def v1(path: str) -> str:
    """把 /api/xxx 换成 /api/v1/xxx。"""
    assert path.startswith("/api/"), path
    return API_V1 + "/" + path[len("/api/"):]


# ---------------------------------------------------------------- 纯函数边界

@pytest.mark.parametrize("path,expected", [
    # 正常改写
    ("/api/v1/tasks", "/api/tasks"),
    ("/api/v1/hub/openmaic/doc", "/api/hub/openmaic/doc"),
    ("/api/v1/diary", "/api/diary"),
    # 尾斜杠属于 rest 的一部分，原样保留
    ("/api/v1/tasks/", "/api/tasks/"),
    ("/api/v1/", "/api/"),
    # 不改写
    ("/api/tasks", None),       # 旧路径本身
    ("/api/v1", None),          # 无尾斜杠：不猜，交给路由层 404
    ("/api/v10/tasks", None),   # 不是 "/api/v1/" 前缀
    ("/api/v1x/tasks", None),
    ("/health/live", None),
    ("/hub", None),
    ("/app", None),
    ("/", None),
    ("/img/a.png", None),
    ("/photos/2026-10/a.jpg", None),
    ("", None),
])
def test_rewrite_path_rules(path, expected):
    """改写规则是纯函数，这里把「恰好 /api/v1/ 前缀」这条边界钉死。"""
    from apiv1 import rewrite_path

    assert rewrite_path(path) == expected


def test_rewrite_path_rejects_non_str():
    from apiv1 import rewrite_path

    assert rewrite_path(None) is None


# ---------------------------------------------------------------- 1. 双路径矩阵

MATRIX = [
    ("/api/tasks", {}),
    ("/api/diary", {"date": "2026-10-20"}),
    ("/api/hub/today", {}),
    ("/api/hub/netinfo", {}),
    ("/api/hub/settings", {}),
    ("/api/usage", {}),
    ("/api/settings", {}),
    ("/api/photos", {}),
    ("/api/ai/context", {}),
]


@pytest.mark.parametrize("path,params", MATRIX, ids=[m[0] for m in MATRIX])
def test_legacy_and_v1_identical(loop_client, path, params):
    """旧路径与 /api/v1 路径必须命中同一个端点，返回完全一致。"""
    old = loop_client.get(path, params=params)
    new = loop_client.get(v1(path), params=params)

    # 先确认不是「两边都 404」这种假通过
    assert old.status_code == 200, "旧路径本身就没通: %s %r" % (old.status_code, old.text[:400])

    detail = "旧: %s %r\n新: %s %r" % (
        old.status_code, old.text[:400], new.status_code, new.text[:400],
    )
    assert old.status_code == new.status_code, "状态码不一致\n" + detail
    assert old.headers.get("content-type") == new.headers.get("content-type"), \
        "content-type 不一致\n" + detail
    assert old.json() == new.json(), "JSON body 不一致\n" + detail


# ---------------------------------------------------------------- 2. 鉴权一致

def test_lan_without_token_401_byte_identical(lan_client):
    """非回环不带 token：v1 路径必须同样 401，且响应体逐字节一致。"""
    old = lan_client.get("/api/hub/settings")
    new = lan_client.get(v1("/api/hub/settings"))

    assert old.status_code == 401, old.text
    assert new.status_code == 401, new.text
    assert old.content == new.content, "401 响应体不一致\n旧: %r\n新: %r" % (old.content, new.content)
    assert new.json().get("error") == "unauthorized"


def test_lan_with_token_allowed_on_both(lan_client):
    old = lan_client.get("/api/hub/settings", headers={"X-Token": TEST_TOKEN})
    new = lan_client.get(v1("/api/hub/settings"), headers={"X-Token": TEST_TOKEN})
    assert old.status_code == 200, old.text
    assert new.status_code == 200, new.text
    assert old.json() == new.json()


def test_lan_with_query_token_allowed_on_both(lan_client):
    """<img>/<a> 无法设请求头，?token= 必须在 v1 路径上同样有效。"""
    old = lan_client.get("/api/hub/settings?token=" + TEST_TOKEN)
    new = lan_client.get(v1("/api/hub/settings") + "?token=" + TEST_TOKEN)
    assert old.status_code == 200, old.text
    assert new.status_code == 200, new.text


def test_loopback_exempt_on_both(loop_client):
    old = loop_client.get("/api/hub/settings")
    new = loop_client.get(v1("/api/hub/settings"))
    assert old.status_code == 200, old.text
    assert new.status_code == 200, new.text


# ---------------------------------------------------------------- 3. 豁免一致

def test_netinfo_exempt_on_both(lan_client):
    """/api/hub/netinfo 免鉴权（App 首次发现服务器时还不知道令牌）。"""
    old = lan_client.get("/api/hub/netinfo")
    new = lan_client.get(v1("/api/hub/netinfo"))
    assert old.status_code != 401, old.text
    assert new.status_code != 401, new.text
    assert old.json() == new.json()


def test_auth_token_forbidden_from_lan_on_both(lan_client):
    """/api/auth/token 非回环必须 403，两条路径的响应体逐字节一致。"""
    old = lan_client.get("/api/auth/token")
    new = lan_client.get(v1("/api/auth/token"))
    assert old.status_code == 403, "非回环取令牌应为 403，实际 %s: %r" % (old.status_code, old.text)
    assert new.status_code == 403, new.text
    assert old.content == new.content, "403 响应体不一致\n旧: %r\n新: %r" % (old.content, new.content)


def test_auth_token_from_loopback_on_both(loop_client):
    old = loop_client.get("/api/auth/token")
    new = loop_client.get(v1("/api/auth/token"))
    assert old.status_code == 200, old.text
    assert new.status_code == 200, new.text
    assert old.json() == new.json()
    assert new.json().get("token") == TEST_TOKEN


# ---------------------------------------------------------------- 4. 边界

def test_unknown_v1_path_404_same_shape(loop_client):
    """/api/v1/no-such → 404，且与旧路径的 404 形状一致（统一错误体）。"""
    old = loop_client.get("/api/no-such")
    new = loop_client.get(API_V1 + "/no-such")
    assert old.status_code == 404, old.text
    assert new.status_code == 404, new.text
    assert old.content == new.content, "404 响应体不一致\n旧: %r\n新: %r" % (old.content, new.content)
    body = new.json()
    assert body["error"]["code"] == "not_found"


def test_bare_v1_is_404_not_redirect(loop_client):
    """/api/v1（无尾斜杠）不改写、不重定向，就是 404。"""
    r = loop_client.get(API_V1, follow_redirects=False)
    assert r.status_code == 404, "预期 404，实际 %s（Location=%r）" % (
        r.status_code, r.headers.get("location"))
    assert r.json()["error"]["code"] == "not_found"


def test_v10_prefix_not_rewritten(loop_client):
    """/api/v10/... 不是 /api/v1/ 前缀，不得被改写。"""
    r = loop_client.get(API_V1 + "0/tasks")
    assert r.status_code == 404, r.text


def test_non_api_paths_untouched(loop_client):
    """改写层不得碰非 /api 路径。"""
    assert loop_client.get("/health/live").status_code == 200
    assert loop_client.get("/").status_code == 200
    assert loop_client.get("/hub").status_code == 200


def test_trailing_slash_still_reaches_working_endpoint(loop_client):
    """带尾斜杠的 v1 请求仍能拿到正常数据（307 跟随后 200）。

    已知形态：`/api/v1/tasks/` → 改写 → `/api/tasks/` → Starlette
    redirect_slashes 307 → `/api/tasks`，**Location 不带 v1 前缀**。

    这里只断言「能正常拿到数据」，不对 Location 的形态做承诺——
    是否把 Location 也改写成 v1 前缀属于"改响应内容"，超出"路径改写"的职责，
    留给 owner 决策；两种决定下这条测试都应当成立。
    """
    r = loop_client.get(API_V1 + "/tasks/")  # follow_redirects 默认 True
    assert r.status_code == 200, r.text
    assert r.json() == loop_client.get("/api/tasks").json()


# ---------------------------------------------------------------- 结构性不变量

def test_route_count_still_73_and_no_v1_routes(app):
    """中间件方案：路由表零新增，且没有任何一条路由自带 /api/v1 前缀。"""
    from dump_routes import dump

    rows = dump(app)
    assert len(rows) == 73, "路由条数变化了：%d（预期 73）" % len(rows)
    v1_rows = [(m, p) for m, p in rows if p.startswith(API_V1)]
    assert not v1_rows, "出现了 /api/v1 路由，说明退化成了路由级别名：%r" % (v1_rows,)


def _middleware_chain(app):
    """从外到内列出中间件：BaseHTTPMiddleware 用 dispatch_func 还原函数名。"""
    names = []
    node = app.build_middleware_stack()
    for _ in range(20):
        if node is None:
            break
        func = getattr(node, "dispatch_func", None)
        names.append(getattr(func, "__name__", type(node).__name__)
                     if func is not None else type(node).__name__)
        node = getattr(node, "app", None)
    return names


def test_alias_runs_before_auth(app):
    """改写层必须在 auth_guard 外层，否则 /api/v1/auth/token 会被 401 打死。"""
    chain = _middleware_chain(app)
    assert "ApiV1AliasMiddleware" in chain, chain
    assert "auth_guard" in chain, chain
    assert chain.index("ApiV1AliasMiddleware") < chain.index("auth_guard"), \
        "中间件顺序错了，改写晚于鉴权：%r" % (chain,)
    # PNA 兜底也要在鉴权内层，保持既有顺序不变
    assert chain.index("auth_guard") < chain.index("allow_private_network"), chain
