# -*- coding: utf-8 -*-
"""M2c-P1/P2：限流与 X-Forwarded-For 的测试。

三组：
  A. 算法单测（Bucket / LoginBackoff / retry_after）——纯函数，可精确断言
  B. XFF 矩阵（受信 / 不受信 / 伪造）——纯函数
  C. 端点级实测（登录退避、上传限频、伪造 XFF 绕不过限流）——起 TestClient
"""
import time

import pytest
from fastapi.testclient import TestClient

import clientip
import ratelimit
from conftest import LAN, LOOP, TEST_TOKEN


# ================================================================== A. 算法
def test_bucket_allows_burst_then_throttles():
    b = ratelimit.Bucket(capacity=3, rate=1.0)
    assert b.take() == 0.0     # 桶初始即满
    assert b.take() == 0.0
    assert b.take() == 0.0
    d = b.take()               # 第 4 个 → 需等 1s 补 1 个 token
    assert 0.9 < d <= 1.0, d


def test_bucket_refills_over_time():
    b = ratelimit.Bucket(capacity=2, rate=10.0)   # 每秒 10 个
    assert b.take() == 0.0
    assert b.take() == 0.0
    assert b.take() > 0
    time.sleep(0.25)           # 0.25s × 10 = 2.5 个 token
    assert b.take() == 0.0
    assert b.take() == 0.0


def test_bucket_capacity_is_hard_cap():
    """补充不能超过容量，否则停一阵之后能攒出超大突发。"""
    b = ratelimit.Bucket(capacity=2, rate=100.0)
    time.sleep(0.2)
    b.take()
    b.take()
    assert b.take() > 0.0, "空桶应被填到容量 2 为止，不允许超过"


def test_bucket_uses_monotonic_not_wall_clock():
    """回拨 wall clock 不能让桶被灌满——这是用 monotonic 的唯一理由。"""
    b = ratelimit.Bucket(capacity=5, rate=1.0)
    for _ in range(5):
        b.take()
    assert b.take() > 0.0
    # 模拟 NTP 回拨：last 被推到未来，delta 变负
    b.last += 3600.0
    assert b.take() > 0.0, "delta 为负时不应补充令牌"


def test_login_backoff_schedule():
    st = ratelimit.LoginBackoff()
    now = time.monotonic()
    for _ in range(4):
        st.record_try(now, 900)
    assert st.delay_for(now, 900, 5, 1.0, 60.0) == 0.0, "未到阈值不该退避"
    st.record_try(now, 900)                 # 第 5 次尝试 → 开始退避
    assert st.delay_for(now, 900, 5, 1.0, 60.0) == pytest.approx(1.0)
    st.record_try(now, 900)
    assert st.delay_for(now, 900, 5, 1.0, 60.0) == pytest.approx(2.0)
    st.record_try(now, 900)
    assert st.delay_for(now, 900, 5, 1.0, 60.0) == pytest.approx(4.0)
    # 指数增长但封顶 60s
    for _ in range(20):
        st.record_try(now, 900)
    assert st.delay_for(now, 900, 5, 1.0, 60.0) == pytest.approx(60.0)


def test_login_backoff_expires_so_user_can_get_back_in():
    """回归：退避**必须会到期**。

    最初的实现按"距上次失败"算 remaining，于是每次 peek 都重新要求等满 1 秒，
    结果连续每秒发一次请求就永远解不了禁——owner 输错 5 次后被永久关在门外。
    这里断言：等够 base 秒之后 delay 归零。
    """
    st = ratelimit.LoginBackoff()
    now = time.monotonic()
    for _ in range(5):
        st.record_try(now, 900)
    assert st.delay_for(now, 900, 5, 1.0, 60.0) > 0
    assert st.delay_for(now + 1.01, 900, 5, 1.0, 60.0) == 0.0, "等够 1 秒后必须解禁"


def test_login_backoff_resets_after_window():
    """15 分钟窗口外 → 不再算"连续"，退避归零。"""
    st = ratelimit.LoginBackoff()
    now = time.monotonic()
    for _ in range(8):
        st.record_try(now, 900)
    assert st.delay_for(now, 900, 5, 1.0, 60.0) > 0
    later = now + 901
    assert st.delay_for(later, 900, 5, 1.0, 60.0) == 0.0
    st.record_try(later, 900)
    assert st.fails == 1, "窗口外的那次尝试应从 1 重新计"


def test_retry_after_never_zero():
    assert ratelimit.retry_after(0.2) == 1, "0 会被客户端当成立即重试"
    assert ratelimit.retry_after(1.9) == 2
    assert ratelimit.retry_after(60.0) == 60


def test_upload_paths_normalize_v1_alias():
    assert ratelimit.is_upload_path("/api/hub/wallpaper")
    assert ratelimit.is_upload_path("/api/photo/upload")
    assert ratelimit.is_upload_path("/api/v1/hub/wallpaper"), "别名路径同样要限"
    assert ratelimit.is_upload_path("/api/v1/photo/upload")
    assert not ratelimit.is_upload_path("/api/hub/settings")
    assert not ratelimit.is_upload_path("/api/photos")


# ================================================================== B. XFF 矩阵
def test_no_trusted_proxies_ignores_xff_entirely(monkeypatch):
    """默认（空列表）→ XFF 完全是噪声。"""
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies([]))
    for xff in ("8.8.8.8", "1.2.3.4", "8.8.8.8, 9.9.9.9, 10.10.10.10"):
        assert clientip.client_ip("192.168.1.50", xff) == "192.168.1.50"


def test_untrusted_source_forging_xff_cannot_change_identity(monkeypatch):
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["10.0.0.0/8"]))
    # 直连来源不在受信列表 → 无论 XFF 写什么都用直连来源
    assert clientip.client_ip("192.168.1.50", "8.8.8.8") == "192.168.1.50"
    assert clientip.client_ip("192.168.1.50", "1.2.3.4, 5.6.7.8") == "192.168.1.50"


def test_trusted_proxy_takes_rightmost_untrusted(monkeypatch):
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["10.0.0.0/8"]))
    # XFF = [伪造的 9.9.9.9, 伪造的 8.8.8.8, 受信代理自己 10.0.0.2]
    # 从右往左：10.0.0.2 受信 → 跳过；8.8.8.8 不受信 → **它就是边界**
    # （右边受信说明这一跳由受控基础设施写入，可信；
    #   更左的 9.9.9.9 是客户端自己写的，不采信）
    assert clientip.client_ip("10.0.0.1", "9.9.9.9, 8.8.8.8, 10.0.0.2") == "8.8.8.8"
    # 只有一跳伪造、一跳受信时同理
    assert clientip.client_ip("10.0.0.1", "9.9.9.9, 10.0.0.2") == "9.9.9.9"


def test_trusted_proxy_single_hop(monkeypatch):
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["10.0.0.0/8"]))
    assert clientip.client_ip("10.0.0.1", "203.0.113.7") == "203.0.113.7"


def test_all_trusted_chain_takes_leftmost(monkeypatch):
    monkeypatch.setattr(clientip, "TRUSTED",
                        clientip.TrustedProxies(["10.0.0.0/8", "172.16.0.0/12"]))
    assert clientip.client_ip("10.0.0.1", "172.16.0.9, 10.0.0.2") == "172.16.0.9"


def test_xff_entries_may_carry_ports(monkeypatch):
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["10.0.0.0/8"]))
    assert clientip.client_ip("10.0.0.1", "203.0.113.7:44321") == "203.0.113.7"
    assert clientip.client_ip("10.0.0.1", "203.0.113.7:44321, 10.0.0.2:8443") == "203.0.113.7"


def test_junk_xff_entries_are_skipped(monkeypatch):
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["10.0.0.0/8"]))
    assert clientip.client_ip("10.0.0.1", "unknown, 203.0.113.7") == "203.0.113.7"
    # 全部非法 → 落回直连来源，不能是 None 或空串
    assert clientip.client_ip("10.0.0.1", "unknown, garbage") == "10.0.0.1"


def test_trusted_proxies_rejects_bad_entries_without_crashing(capsys):
    t = clientip.TrustedProxies(["10.0.0.0/8", "not-an-ip", "", "  "])
    assert len(t.nets) == 1
    assert "not-an-ip" in capsys.readouterr().out, "非法条目必须留证据，否则会静默退化"


def test_trusted_proxies_version_mismatch_is_not_crash():
    """IPv4 受信表遇到 IPv6 客户端 → 判为不受信，不抛异常。"""
    import ipaddress
    t = clientip.TrustedProxies(["10.0.0.0/8"])
    assert ipaddress.ip_address("2001:db8::1") not in t


# ================================================================== C. 端点级
# TestClient 的来源 IP 在**构造时**固定（client=LAN），不是每次请求传参。
# 换 IP 就得换一个 client，因此统一走 make_client。
def make_client(peer):
    import main
    return TestClient(main.app, client=peer)


@pytest.fixture
def clean_limit(store):
    """干净限流器 + 临时账号。

    账号是**必须**的：没有账号时 /api/auth/login 返回 503（设计行为），
    退避分支根本走不到，整个用例就变成在测 503。
    """
    import auth_sessions
    auth_sessions.set_password("unit-test-owner", "unit-test-only-not-a-real-secret",
                              revoke_sessions=True)
    ratelimit.LIMITER.reset()
    yield
    ratelimit.LIMITER.reset()


def _post_login(c, username="unit-test-owner", password="wrong-pw", headers=None):
    h = dict(headers or {})
    return c.post("/api/auth/login", json={"username": username, "password": password}, headers=h)


def test_login_backoff_escalates_to_429(clean_limit):
    c = make_client(LAN)
    # 前 5 次：401
    for i in range(5):
        r = _post_login(c)
        assert r.status_code == 401, "第 %d 次应为 401，实际 %d" % (i + 1, r.status_code)
    # 第 6 次起：429 + Retry-After
    r = _post_login(c)
    assert r.status_code == 429, r.text
    ra = r.headers.get("Retry-After")
    assert ra is not None and int(ra) >= 1
    assert r.json()["error"]["code"] == "too_many_requests"
    assert _post_login(c).status_code == 429, "退避期内持续 429"


def test_login_backoff_is_per_ip_and_per_account(clean_limit):
    """换 IP 或换账号 → 退避不共享。"""
    c = make_client(LAN)
    for _ in range(6):
        _post_login(c)
    assert _post_login(c).status_code == 429
    c2 = make_client(("10.1.2.3", 51234))
    assert _post_login(c2).status_code == 401, "换 IP 后不该继承退避"
    assert _post_login(c, username="someone-else").status_code == 401, "换账号不该继承退避"


def test_loopback_never_rate_limited(clean_limit):
    """本机桌面端不受限——否则开发者先被自己锁死。"""
    c = make_client(LOOP)
    for _ in range(40):
        r = _post_login(c)
        assert r.status_code in (401, 503), "回环不该收到 429，实际 %d" % r.status_code


def test_api_bucket_limits_burst_from_one_ip(clean_limit):
    c = make_client(LAN)
    h = {"X-Token": TEST_TOKEN}
    codes = [c.get("/api/hub/settings", headers=h).status_code for _ in range(140)]
    assert 429 in codes, "140 次请求应撞满桶"
    first_429 = codes.index(429)
    assert first_429 <= 130, "不该放任太久才限流，实际第 %d 次才 429" % first_429


def test_api_bucket_is_per_ip(clean_limit):
    c = make_client(LAN)
    h = {"X-Token": TEST_TOKEN}
    for _ in range(80):
        c.get("/api/hub/settings", headers=h)
    c2 = make_client(("10.9.9.9", 51234))
    assert c2.get("/api/hub/settings", headers=h).status_code == 200, "别的 IP 不该被牵连"


def test_upload_path_is_limited_tighter(clean_limit):
    """上传限频独立于全局桶，且阈值更小。"""
    c = make_client(LAN)
    h = {"X-Token": TEST_TOKEN}
    codes = [c.post("/api/hub/wallpaper", json={"data": ""}, headers=h).status_code
             for _ in range(8)]
    assert 429 in codes, codes


def test_forged_xff_cannot_bypass_login_backoff(clean_limit, monkeypatch):
    """核心安全断言：不受信来源伪造 XFF 必须**绕不过**退避。"""
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["10.0.0.0/8"]))
    c = make_client(LAN)          # 直连来源 192.168.1.50 → 不受信
    for _ in range(5):
        _post_login(c)
    # 每次换一个伪造 IP —— 若实现错误地采信 XFF，下面每一次都会是 401
    for i in range(5):
        r = _post_login(c, headers={"X-Forwarded-For": "203.0.113.%d" % i})
        assert r.status_code == 429, "第 %d 次伪造 XFF 绕过了限流（%d）" % (i, r.status_code)


def test_trusted_proxy_xff_is_honoured(clean_limit, monkeypatch):
    """受信直连来源 → XFF 生效，两次请求算在**同一个**客户端 IP 上。"""
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["10.0.0.0/8"]))
    c = make_client(("10.0.0.1", 51234))     # 直连来源受信
    # 同一个"真实客户端"（XFF 恒为 198.51.100.9）错 5 次
    for _ in range(5):
        _post_login(c, headers={"X-Forwarded-For": "198.51.100.9"})
    # 第 6 次：无论 XFF 里写的是谁，都算在 198.51.100.9 头上 → 退避
    assert _post_login(c, headers={"X-Forwarded-For": "198.51.100.9"}).status_code == 429
    assert _post_login(c, headers={"X-Forwarded-For": "198.51.100.9"}).status_code == 429
    # 换成**另一个**真实客户端 → 独立计数，第 1 次仍是 401
    r2 = _post_login(c, headers={"X-Forwarded-For": "198.51.100.10"})
    assert r2.status_code == 401, "另一个真实客户端不该被牵连"


def test_429_shape_is_distinct_from_401(clean_limit):
    """429 与 401 形状必须可区分：前端靠它决定"重登"还是"等"。"""
    c = make_client(LAN)
    r = _post_login(c)
    assert r.status_code == 401
    assert r.json().get("detail") == "用户名或口令错误"
    for _ in range(5):
        _post_login(c)
    r = _post_login(c)
    assert r.status_code == 429
    body = r.json()
    # 端点抛的 HTTPException 经 errors.py 归一化：code=too_many_requests，
    # Retry-After 走**响应头**（中间件侧才带 body 里的 retry_after，
    # 两者都由前端按 status_code + 头判断，不依赖 body 的具体形状）。
    assert body["error"]["code"] == "too_many_requests"
    assert int(r.headers["Retry-After"]) >= 1


def test_429_carries_retry_after_header(clean_limit):
    c = make_client(LAN)
    for _ in range(6):
        _post_login(c)
    r = _post_login(c)
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers.keys()}


def test_login_success_clears_backoff(clean_limit, store):
    """成功登录 → 计数清零，之后再错 5 次才重新退避。"""
    good_pw = "unit-test-only-not-a-real-secret"
    c = make_client(LAN)
    # 错 4 次（还没到阈值），第 5 次用正确口令 → 应成功并清零
    for _ in range(4):
        assert _post_login(c).status_code == 401
    ok = _post_login(c, password=good_pw)
    assert ok.status_code == 200, ok.text
    for _ in range(5):
        r = _post_login(c)
        assert r.status_code == 401, "成功后计数应清零，重新数满 5 次"
    assert _post_login(c).status_code == 429


def test_options_preflight_not_rate_limited(clean_limit):
    c = make_client(LAN)
    for _ in range(50):
        r = c.options("/api/hub/settings",
                      headers={"Origin": "http://x", "Access-Control-Request-Method": "GET"})
        assert r.status_code != 429, "CORS 预检被限流会给浏览器制造随机失败"


def test_api_bucket_covers_v1_alias_paths(clean_limit):
    """/api/v1/* 与 /api/* 落到同一个桶，不能只挡一边。"""
    c = make_client(LAN)
    h = {"X-Token": TEST_TOKEN}
    codes = []
    for _ in range(140):
        codes.append(c.get("/api/v1/hub/settings", headers=h).status_code)
    assert 429 in codes, "别名路径也必须计入限流"
