# -*- coding: utf-8 -*-
"""M2c-P4：安全响应头与 CSP 的测试。

三组：
  A. 常量与策略形状（纯函数）
  B. meta 与响应头**一致性**（两处 CSP 漂移是最隐蔽的坑，必须锁死）
  C. 端点级实测（头是否真的下发、下发在哪些路径、401/429 上也在）
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

import security_headers
from conftest import LAN, TEST_TOKEN
from main import app

client = TestClient(app)

INDEX_HTML = Path(__file__).resolve().parents[2] / "web" / "index.html"


def _get(path, **kw):
    kw.setdefault("headers", {"X-Token": TEST_TOKEN})
    return client.get(path, **kw)


# ================================================================== A. 形状
def test_csp_header_is_meta_plus_frame_ancestors():
    assert security_headers.CSP_HEADER == security_headers.CSP_META + "; frame-ancestors 'none'"


def test_no_unsafe_inline_in_script_or_style_elem():
    """script-src 与 style-src 不得有 unsafe-inline/unsafe-eval——那才等于没设 CSP。

    唯一允许 unsafe-inline 的是 **style-src-attr**（只管 style 属性，
    不管 <style> 与样式表），且必须有 style-src 'self' 兜住 elem。
    """
    # 把 style-src-attr 整条摘掉再查，剩下的指令一条 unsafe-inline 都不能有
    rest = re.sub(r"style-src-attr[^;]*;?\s*", "", security_headers.CSP_META)
    assert "unsafe-inline" not in rest, rest
    assert "unsafe-eval" not in rest
    assert "unsafe-hashes" not in rest
    assert "*" not in security_headers.CSP_META


def test_style_src_attr_is_the_only_unsafe_inline():
    """锁住这条取舍：style-src-attr 开，style-src / script-src 保持 'self'。"""
    csp = security_headers.CSP_META
    assert "style-src-attr 'unsafe-inline'" in csp
    assert "style-src 'self'" in csp
    assert "script-src 'self'" in csp
    # 顺序上 style-src 必须在 style-src-attr 之前，
    # 否则浏览器会把 style-src-attr 当成 style-src 的补充说明而非独立指令。
    assert csp.index("style-src 'self'") < csp.index("style-src-attr")


def test_csp_directives_all_present():
    for d in ("default-src", "script-src", "style-src", "img-src",
              "font-src", "connect-src", "media-src", "object-src",
              "frame-src", "base-uri", "form-action"):
        assert d + " " in security_headers.CSP_META + " ", d


def test_object_and_frame_are_none():
    assert "object-src 'none'" in security_headers.CSP_META
    assert "frame-src 'none'" in security_headers.CSP_META


def test_connect_src_allows_http_for_lan_api():
    """APK 场景 API 在 LAN IP 上（http），connect-src 必须放行 http。"""
    assert "connect-src 'self' http: https:" in security_headers.CSP_META


def test_img_src_covers_data_blob_http():
    for tok in ("data:", "blob:", "http:", "https:"):
        assert tok in re.search(r"img-src ([^;]+);", security_headers.CSP_META).group(1)


def test_should_send_csp_paths():
    assert security_headers.should_send_csp("/app")
    assert security_headers.should_send_csp("/app/index.html")
    assert security_headers.should_send_csp("/app/assets/index-abc.js")
    # 旧 /hub 有内联 style/script，**不能**给 CSP，否则直接打挂
    assert not security_headers.should_send_csp("/hub")
    assert not security_headers.should_send_csp("/hub/x.css")
    assert not security_headers.should_send_csp("/api/summary")
    assert not security_headers.should_send_csp("/photos/a.jpg")


# ================================================================== B. 两处一致
def test_meta_in_index_html_exists_and_matches_header():
    html = INDEX_HTML.read_text(encoding="utf-8")
    m = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
    assert m, "web/index.html 里没有 meta CSP"
    meta = m.group(1)
    # 浏览器对 meta 与响应头**取交集**，两者不一致 ≠ 更严，而是"看起来配了其实没约束住"。
    # 允许 header 多出 frame-ancestors（meta 里写了也不生效），其余必须逐字相同。
    assert meta == security_headers.CSP_META, "meta CSP 与 CSP_META 漂移了"
    assert security_headers.CSP_HEADER == meta + "; frame-ancestors 'none'"


def test_meta_csp_has_no_frame_ancestors():
    """frame-ancestors 在 meta 里会被忽略，写了是自欺。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    m = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
    assert "frame-ancestors" not in m.group(1)


def test_always_headers_values():
    assert security_headers.ALWAYS_HEADERS["Referrer-Policy"] == "no-referrer"
    assert security_headers.ALWAYS_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert security_headers.ALWAYS_HEADERS["X-Frame-Options"] == "DENY"


# ================================================================== C. 端点
def test_app_index_sends_csp_header():
    r = _get("/app")
    if r.status_code == 404:
        return          # SPA 未构建时跳过（本仓库已提交产物，正常不会走到）
    assert r.status_code == 200
    assert r.headers["Content-Security-Policy"] == security_headers.CSP_HEADER
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_app_assets_send_csp_header():
    r = _get("/app/")
    assert "Content-Security-Policy" in r.headers


def test_hub_does_not_send_csp_header():
    """旧页有内联脚本，给 CSP 会打挂——用测试锁住这个决定，别被后人"顺手补上"。"""
    r = _get("/hub")
    if r.status_code == 404:
        return
    assert "Content-Security-Policy" not in r.headers
    # 但通用安全头照发
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_api_response_has_security_headers():
    r = _get("/api/summary")
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_headers_present_on_401():
    """鉴权失败是浏览器最先看到的响应之一，不能缺头。/app 不鉴权，用 /api 触发。"""
    r = client.get("/api/summary")
    assert r.status_code == 401
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_headers_present_on_429():
    """限流触发时的 429 也必须带头。"""
    from ratelimit import LIMITER
    orig = LIMITER.api_take
    LIMITER.api_take = lambda ip: 30.0      # 抽干令牌桶，必得 429
    try:
        r = client.get("/api/summary", headers={"X-Token": TEST_TOKEN})
    finally:
        LIMITER.api_take = orig
    assert r.status_code == 429
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "Retry-After" in r.headers


def test_lan_client_gets_same_headers():
    """非回环请求（真实公网场景）同样带头。"""
    # TestClient 的来源 IP 在**构造时**固定，不能按请求传参。
    from fastapi.testclient import TestClient
    import main
    lan = TestClient(main.app, client=LAN)
    r = lan.get("/app", headers={"X-Token": TEST_TOKEN})
    assert r.status_code in (200, 404)
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"