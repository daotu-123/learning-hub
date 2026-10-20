# -*- coding: utf-8 -*-
"""M2c-P3：媒体路径鉴权 + 短时签名 URL。

覆盖三条历史裸奔的路径：/img/*、/photos/*、/api/hub/wallpapers/*
"""
import time

import pytest
from fastapi.testclient import TestClient

import media_sign
from conftest import LAN, LOOP, TEST_TOKEN

# 签名不依赖真实文件，所以用这些不存在的路径也能验鉴权行为
IMG_PATH = "/img/attachments/2026/08/photo.png"
PHOTO_PATH = "/photos/2026-08/photo.jpg"
WALL_PATH = "/api/hub/wallpapers/custom-2026-08-01-abcd1234.jpg"


@pytest.fixture
def clean_sign(monkeypatch, tmp_path):
    """把密钥文件指到临时目录 + 清掉模块缓存，绝不碰真实数据目录。"""
    p = tmp_path / "media_url_secret"
    p.write_bytes(b"unit-test-only-media-secret-0123456789")
    monkeypatch.setattr(media_sign, "SECRET_FILE", p)
    monkeypatch.setattr(media_sign, "_cache", None)
    yield
    media_sign._cache = None


def make_client(peer):
    import main
    return TestClient(main.app, client=peer)


# ================================================================== 鉴权
def test_media_paths_require_auth_from_lan(clean_sign):
    """核心：非回环访问媒体路径必须 401。这是修掉的真实漏洞。"""
    c = make_client(LAN)
    for path in (IMG_PATH, PHOTO_PATH, WALL_PATH):
        r = c.get(path)
        assert r.status_code == 401, "%s 未被鉴权拦截（%d）" % (path, r.status_code)
        assert r.json()["error"] == "unauthorized", "401 形状必须与既有逐字节一致"


def test_media_401_body_is_identical_to_api_401(clean_sign):
    """媒体 401 与 /api/ 401 必须是同一份字面量，前端才能统一处理。"""
    c = make_client(LAN)
    a = c.get(IMG_PATH)
    b = c.get("/api/hub/settings")
    assert a.status_code == b.status_code == 401
    assert a.content == b.content


def test_media_paths_open_on_loopback(clean_sign):
    """本机桌面端预览照片不该要令牌——否则每次看图都要登录。"""
    c = make_client(LOOP)
    for path in (IMG_PATH, PHOTO_PATH, WALL_PATH):
        r = c.get(path)
        assert r.status_code != 401, "%s 在回环被拦了" % path


def test_media_accepts_legacy_token_header(clean_sign):
    """双轨过渡：旧共享令牌也能看媒体，否则已发布 APK 的图全挂。"""
    c = make_client(LAN)
    r = c.get(PHOTO_PATH, headers={"X-Token": TEST_TOKEN})
    assert r.status_code != 401, "旧 X-Token 应当仍然有效"


def test_media_accepts_session_bearer(clean_sign, store):
    """会话令牌（Bearer 头）同样有效。"""
    import auth_sessions
    auth_sessions.set_password("unit-test-owner", "unit-test-only-not-a-real-secret",
                              revoke_sessions=True)
    tok, _ = auth_sessions.create_session(user_agent="pytest", username="unit-test-owner")
    c = make_client(LAN)
    r = c.get(PHOTO_PATH, headers={"Authorization": "Bearer " + tok})
    assert r.status_code != 401, "会话 Bearer 应当有效"


def test_media_rejects_bogus_token(clean_sign):
    c = make_client(LAN)
    assert c.get(PHOTO_PATH, headers={"X-Token": "wrong-token"}).status_code == 401
    assert c.get(PHOTO_PATH, headers={"Authorization": "Bearer wrong-session"}).status_code == 401


def test_media_paths_are_rate_limited(clean_sign):
    """签名 URL 也在限流范围内，否则拿到签名就能无限刷图。"""
    import ratelimit
    ratelimit.LIMITER.reset()
    try:
        c = make_client(LAN)
        codes = [c.get(PHOTO_PATH, headers={"X-Token": TEST_TOKEN}).status_code
                 for _ in range(160)]
        assert 429 in codes, "媒体路径必须计入限流"
    finally:
        ratelimit.LIMITER.reset()


def test_static_pages_still_open_without_auth(clean_sign):
    """媒体纳入鉴权**不能**顺手把页面也关掉——静态资源仍然放行。"""
    c = make_client(LAN)
    for path in ("/", "/api/hub/netinfo"):
        assert c.get(path).status_code == 200, path


# ================================================================== 签名
def test_signed_url_grants_access(clean_sign):
    c = make_client(LAN)
    s = media_sign.signed(PHOTO_PATH)["url"]
    assert c.get(s).status_code != 401, "有效签名应放行"
    assert "token" not in s, "签名 URL 里绝不能出现 token 参数"


def test_signed_url_has_sig_and_exp_only(clean_sign):
    s = media_sign.signed(PHOTO_PATH)
    url = s["url"]
    assert "sig=" in url and "exp=" in url
    assert "token" not in url.lower()


def test_signature_is_bound_to_path(clean_sign):
    """A 图的签名不能用来访问 B 图。

    纯函数层断言"签名对不上"（这才是绑定语义）；
    HTTP 层再断言**没有落到 401** —— 因为中间件先验签，验签过了才会到路由，
    路由因文件不存在返回 404。断言 401 反而会漏掉"验签其实过了"的情况。
    """
    a = media_sign.signed(PHOTO_PATH)
    sig_a = a["url"].split("sig=")[1].split("&")[0]
    assert not media_sign.verify(IMG_PATH, a["expires_at"], sig_a), "签名必须绑定 path"
    # HTTP 层：把 URL 里的路径换成 IMG_PATH，签名对不上 → 401
    b_path = a["url"].replace(PHOTO_PATH, IMG_PATH)
    assert make_client(LAN).get(b_path).status_code == 401


def test_expired_signature_rejected(clean_sign):
    expired = int(time.time()) - 10
    sig = media_sign.sign(PHOTO_PATH, expired)
    r = make_client(LAN).get("%s?sig=%s&exp=%d" % (PHOTO_PATH, sig, expired))
    assert r.status_code == 401, "过期签名必须失效"


def test_tampered_signature_rejected(clean_sign):
    s = media_sign.signed(PHOTO_PATH)
    bad = s["url"][:-4] + "AAAA"
    assert make_client(LAN).get(bad).status_code == 401


def test_signature_ignores_extra_exp_bump(clean_sign):
    """改 exp 试图延长有效期 → 签名对不上。"""
    s = media_sign.signed(PHOTO_PATH)
    tampered = s["url"] + ""
    import re as _re
    tampered = _re.sub(r"exp=\d+", "exp=%d" % (int(time.time()) + 3000), tampered)
    assert make_client(LAN).get(tampered).status_code == 401, "exp 参与签名，不能改"


def test_ttl_capped_at_five_minutes(clean_sign):
    s = media_sign.signed(PHOTO_PATH, ttl=86400)
    assert s["expires_at"] - int(time.time()) <= media_sign.MAX_TTL_SECONDS


def test_default_ttl_is_five_minutes(clean_sign):
    assert media_sign.DEFAULT_TTL_SECONDS == 300
    assert media_sign.MAX_TTL_SECONDS == 300


# ================================================================== 签名下发接口
def _sign_post(c, paths, **kw):
    return c.post("/api/media/sign", json={"paths": paths}, **kw)


def test_sign_endpoint_requires_auth(clean_sign):
    c = make_client(LAN)
    assert _sign_post(c, [PHOTO_PATH]).status_code == 401


def test_sign_endpoint_returns_signed_urls(clean_sign):
    c = make_client(LAN)
    h = {"X-Token": TEST_TOKEN}
    r = _sign_post(c, [PHOTO_PATH, IMG_PATH], headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2
    for it in items:
        assert "sig=" in it["url"] and "token" not in it["url"]
    # 签出来的 URL 立刻能用
    assert c.get(items[0]["url"]).status_code != 401


@pytest.mark.parametrize("bad", [
    "../etc/passwd",
    "/img/../../etc/passwd",
    "/photos/../../secret.txt",
    "img/no-leading-slash.png",
    "//evil.example/x.png",
    "/img/a\\b.png",
    "/api/hub/settings",          # 不是媒体路径
    "/photos/x.txt",              # 非图片扩展名
    "/photos/x?token=abc",        # 不得带 query
])
def test_sign_endpoint_rejects_unsafe_paths(clean_sign, bad):
    """路径穿越防线。签名 = 授权读这个确切路径，签错就是新的读取口。"""
    c = make_client(LAN)
    r = _sign_post(c, [bad], headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 400, "非法路径应被拒：%r 实际 %d" % (bad, r.status_code)


def test_sign_endpoint_caps_batch_size(clean_sign):
    """防止把它当批量签发器用。"""
    c = make_client(LAN)
    h = {"X-Token": TEST_TOKEN}
    r = _sign_post(c, [PHOTO_PATH] * 500, headers=h)
    assert len(r.json()["items"]) <= 200


def test_photo_list_returns_signed_urls(clean_sign, tmp_path, monkeypatch):
    """/api/photos 返回的 url 必须可直接放进 <img src>。"""
    import routers.media as media_mod
    vault = tmp_path / "vault"
    photos_dir = vault / "工作台照片" / "2026-08"
    photos_dir.mkdir(parents=True)
    (photos_dir / "pic.jpg").write_bytes(b"\xff\xd8\xff test")
    # 端点用 OBSIDIAN_VAULT 计算相对路径，所以 vault 根也要一起指过去，
    # 否则 p.relative_to(OBSIDIAN_VAULT) 会抛 ValueError。
    monkeypatch.setattr(media_mod, "OBSIDIAN_VAULT", vault)
    monkeypatch.setattr(media_mod, "PHOTO_ROOT", vault / "工作台照片")
    c = make_client(LAN)
    r = c.get("/api/photos", headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 200, r.text
    photos = r.json()["photos"]
    assert photos, "应至少列出一张照片"
    u = photos[0]["url"]
    assert "sig=" in u and "token" not in u
    assert photos[0]["path_url"] == "/photos/2026-08/pic.jpg"
    # 签名 URL 真的能取到字节
    got = c.get(u)
    assert got.status_code == 200, got.status_code
    assert got.content == b"\xff\xd8\xff test"


def test_sig_is_masked_in_access_logs(clean_sign):
    """签名参数必须走既有的日志脱敏（token|sig 都在正则里）。"""
    from logging_setup import mask_query
    s = media_sign.signed(PHOTO_PATH)
    masked = mask_query("GET %s HTTP/1.1" % s["url"])
    assert "sig=***" in masked
    sig_value = s["url"].split("sig=")[1].split("&")[0]
    assert sig_value not in masked
