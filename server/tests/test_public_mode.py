# -*- coding: utf-8 -*-
"""M3-P5：公网模式（`HUB_PUBLIC=1`）。

四条规则逐条有测试，缺一不可：
  1. 监听缺省收成 127.0.0.1
  2. UDP 自动发现广播关闭
  3. **回环免鉴权豁免关闭** ← 最高危，隧道流量看起来来自 127.0.0.1
  4. 未显式设 HUB_DATA_DIR → 拒绝启动（退出码 3）

外加"客户端真实 IP"规则：只有直连来源受信时才采信代理头。

最重要的一条回归保护在最后一节：**未设 HUB_PUBLIC 时行为必须与之前逐字一致**，
否则本机/局域网桌面端与整套测试一起崩。

测试技巧：client_ip() 读模块级 TRUSTED，用 monkeypatch 换掉；
豁免判定读环境变量，用 monkeypatch.setenv。
"""
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import clientip
import config
import publicmode
from conftest import TEST_TOKEN
from publicmode import EXIT_PUBLIC_GUARD

SERVER_DIR = Path(__file__).resolve().parent.parent
LOOP = ("127.0.0.1", 40001)          # 隧道/反代回源时看起来就是这样
LAN = ("192.168.1.77", 40002)


@pytest.fixture
def client():
    """来源 = 非回环（LAN），默认需要令牌。"""
    from main import app

    return TestClient(app, client=LAN)


@pytest.fixture
def loop_client():
    """来源 = 回环。隧道/反代回源时看起来就是这样，公网模式的核心场景。"""
    from main import app

    return TestClient(app, client=LOOP)


@pytest.fixture
def no_env(monkeypatch):
    """确保 HUB_PUBLIC / HUB_LOCAL_BYPASS 都没设（绝大多数用例的基线）。"""
    for k in ("HUB_PUBLIC", "HUB_LOCAL_BYPASS", "HUB_DATA_DIR"):
        monkeypatch.delenv(k, raising=False)


# ====================================================================
# 0. 纯函数层：不依赖 app
# ====================================================================

def test_local_bypass_is_on_without_public_mode(no_env):
    """未设 HUB_PUBLIC → 回环豁免开启（历史行为，逐字不变）。"""
    assert publicmode.local_bypass_enabled() is True


def test_local_bypass_off_in_public_mode(monkeypatch):
    monkeypatch.setenv("HUB_PUBLIC", "1")
    monkeypatch.delenv("HUB_LOCAL_BYPASS", raising=False)
    assert publicmode.local_bypass_enabled() is False


def test_local_bypass_on_in_public_mode_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("HUB_PUBLIC", "1")
    monkeypatch.setenv("HUB_LOCAL_BYPASS", "1")
    assert publicmode.local_bypass_enabled() is True


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", "On"])
def test_truthy_spellings(monkeypatch, val):
    monkeypatch.setenv("HUB_PUBLIC", val)
    assert publicmode.local_bypass_enabled() is False   # 公网模式生效 = 豁免关


@pytest.mark.parametrize("val", ["", " ", "0", "false", "no", "off", "2", "yes please"])
def test_non_public_spellings_keep_legacy(monkeypatch, val):
    """模糊写法一律当"没开公网模式" → 豁免保持历史行为。

    这类开关配错的后果不对称：HUB_PUBLIC 误开会让服务关掉回环豁免、
    绑到 127.0.0.1 但隧道又没通（服务等于没上线）。
    """
    monkeypatch.setenv("HUB_PUBLIC", val)
    assert publicmode.local_bypass_enabled() is True


def test_udp_discovery_off_in_public_mode():
    assert publicmode.udp_discovery_enabled(public=True) is False


def test_udp_discovery_on_without_public_mode():
    assert publicmode.udp_discovery_enabled(public=False) is True


# ====================================================================
# 1. 硬闸：HUB_PUBLIC=1 且未设 HUB_DATA_DIR → 拒绝启动
# ====================================================================

def test_guard_blocks_when_public_without_data_dir(monkeypatch, capsys):
    monkeypatch.setenv("HUB_PUBLIC", "1")
    monkeypatch.delenv("HUB_DATA_DIR", raising=False)
    rc = publicmode.startup_public_guard()
    assert rc == EXIT_PUBLIC_GUARD != 0
    err = capsys.readouterr().err
    assert "拒绝启动：公网模式（HUB_PUBLIC=1）必须显式指定数据目录" in err
    assert "HUB_DATA_DIR" in err


def test_guard_passes_when_data_dir_set(monkeypatch):
    monkeypatch.setenv("HUB_PUBLIC", "1")
    monkeypatch.setenv("HUB_DATA_DIR", r"D:\LearningHub\data")
    assert publicmode.startup_public_guard() == 0


def test_guard_ignores_blank_data_dir(monkeypatch, capsys):
    """空串/纯空白 = 没设置，必须照样拦。"""
    monkeypatch.setenv("HUB_PUBLIC", "1")
    monkeypatch.setenv("HUB_DATA_DIR", "   ")
    assert publicmode.startup_public_guard() == EXIT_PUBLIC_GUARD


def test_guard_passes_without_public_mode(monkeypatch):
    """未设 HUB_PUBLIC → 直接放行，一个字都不打印。"""
    monkeypatch.delenv("HUB_PUBLIC", raising=False)
    monkeypatch.delenv("HUB_DATA_DIR", raising=False)
    assert publicmode.startup_public_guard() == 0


def test_guard_exit_code_distinct_from_manage_cli():
    """硬闸 3 与 manage.py 防呆 2 不能撞车——调用方要能区分是谁拒绝的。"""
    from manage import EXIT_REFUSED_DEFAULT_DIR

    assert EXIT_PUBLIC_GUARD != EXIT_REFUSED_DEFAULT_DIR


def test_guard_really_blocks_process_start(tmp_path):
    """子进程真跑一次：HUB_PUBLIC=1 + 无 HUB_DATA_DIR 必须退出且非 0。"""
    env = {
    "PATH": r"C:\Windows\System32",
    "SYSTEMROOT": r"C:\Windows",
    "PYTHONPATH": str(SERVER_DIR),
    "HUB_PUBLIC": "1",
    "HUB_DATA_DIR": "",             # 显式给空 = 未设置
    "PYTHONIOENCODING": "utf-8",
    }
    r = subprocess.run(
    [sys.executable, "-c",
         "import sys; from publicmode import startup_public_guard;"
         " sys.exit(startup_public_guard())"],
    cwd=str(SERVER_DIR), env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert r.returncode == EXIT_PUBLIC_GUARD, (r.returncode, r.stdout, r.stderr)
    assert "拒绝启动：公网模式（HUB_PUBLIC=1）必须显式指定数据目录" in r.stderr


def test_guard_passes_process_when_data_dir_given(tmp_path):
    """对照组：给了 HUB_DATA_DIR 就放行，退出码 0。"""
    env = {
    "PATH": r"C:\Windows\System32",
    "SYSTEMROOT": r"C:\Windows",
    "PYTHONPATH": str(SERVER_DIR),
    "HUB_PUBLIC": "1",
    "HUB_DATA_DIR": str(tmp_path / "data"),
    "PYTHONIOENCODING": "utf-8",
    }
    r = subprocess.run(
    [sys.executable, "-c",
         "import sys; from publicmode import startup_public_guard;"
         " sys.exit(startup_public_guard())"],
    cwd=str(SERVER_DIR), env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


# ====================================================================
# 2. app 层：回环豁免在公网模式下必须关掉
# ====================================================================

def test_public_mode_loopback_without_token_is_401(loop_client, monkeypatch):
    """**最高危那条**：公网模式下来源 127.0.0.1 且不带令牌 → 401。

    隧道（cloudflared / tailscale funnel）回源就是 127.0.0.1。
    豁免若没关，这条请求会返回 200 —— 公网裸奔。
    """
    monkeypatch.setattr(publicmode, "local_bypass_enabled", lambda *a, **k: False)
    r = loop_client.get("/api/summary")
    assert r.status_code == 401, r.text
    # 401 形状一个字不许改
    assert r.json()["error"] == "unauthorized"
    assert "hint" in r.json()


def test_public_mode_loopback_with_fake_proxy_headers_is_401(loop_client, monkeypatch):
    """伪装 CF-Connecting-IP / XFF 也不能免鉴权。

    攻击者的位置：经隧道进来时这两个头都是他自己能写的。
    豁免判定只看"来源是不是回环"，**不看任何请求头**——
    所以伪造头在这里毫无作用，这正是要验的。
    """
    monkeypatch.setattr(publicmode, "local_bypass_enabled", lambda *a, **k: False)
    for headers in (
        {"CF-Connecting-IP": "1.2.3.4"},
        {"X-Forwarded-For": "1.2.3.4"},
        {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"},
        {"X-Real-IP": "127.0.0.1"},
        {"Host": "hub.example.com"},
    ):
        r = loop_client.get("/api/summary", headers=headers)
        assert r.status_code == 401, (headers, r.text)


def test_public_mode_loopback_with_token_is_200(loop_client, monkeypatch):
    """对照组：公网模式下带对令牌就放行（否则公网模式不可用）。"""
    monkeypatch.setattr(publicmode, "local_bypass_enabled", lambda *a, **k: False)
    r = loop_client.get("/api/summary", headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 200, r.text


def test_public_mode_loopback_is_rate_limited(loop_client, monkeypatch):
    """豁免关了之后，回环请求也进限流桶。

    这条容易被忽略：只关鉴权不关限流的话，回环流量虽然需要令牌，
    但仍可把桶打满——而桶是按客户端 IP 计的，公网模式下所有隧道流量
    共享同一个"客户端"（取决于代理头处理），后果是所有人被连坐。
    """
    import ratelimit

    monkeypatch.setattr(publicmode, "local_bypass_enabled", lambda *a, **k: False)
    ratelimit.LIMITER.reset()
    r = loop_client.get("/api/summary", headers={"X-Token": TEST_TOKEN})
    assert r.status_code == 200
    # 再打满：桶容量有限，应出现 429
    got429 = False
    for _ in range(200):
        rr = loop_client.get("/api/summary", headers={"X-Token": TEST_TOKEN})
        if rr.status_code == 429:
            got429 = True
            break
    assert got429, "公网模式下回环请求未被限流"


def test_non_public_mode_loopback_still_exempt(loop_client, no_env, monkeypatch):
    """**回归保护**：未设 HUB_PUBLIC 时回环免令牌仍然生效。"""
    r = loop_client.get("/api/summary")
    assert r.status_code == 200, r.text


def test_non_public_mode_loopback_not_rate_limited(loop_client, no_env, monkeypatch):
    """回归保护：未设 HUB_PUBLIC 时回环不被限流。"""
    import ratelimit

    ratelimit.LIMITER.reset()
    codes = {loop_client.get("/api/summary").status_code for _ in range(120)}
    assert codes == {200}, codes


# ====================================================================
# 3. 客户端真实 IP：受信代理 vs 伪造
# ====================================================================

def test_trusted_proxy_cf_connecting_ip_is_used(monkeypatch):
    """受信代理 + CF-Connecting-IP → 采信它（cloudflared 场景）。"""
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["127.0.0.1"]))
    assert clientip.client_ip("127.0.0.1", "203.0.113.9") == "203.0.113.9"
    assert clientip.peer_is_trusted("127.0.0.1") is True


def test_trusted_proxy_xff_rightmost_untrusted(monkeypatch):
    """XFF 链里从右往左取第一个非受信地址。"""
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["127.0.0.1", "10.0.0.0/8"]))
    # 客户端伪造最左边的值，真实 IP 在最右边
    assert clientip.client_ip("127.0.0.1", "6.6.6.6, 10.0.0.5, 127.0.0.1") == "6.6.6.6"


def test_untrusted_peer_forged_xff_ignored(monkeypatch):
    """**不受信来源伪造 XFF 无效** —— 按真实直连 IP 计。"""
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["127.0.0.1"]))
    assert clientip.client_ip("203.0.113.66", "6.6.6.6") == "203.0.113.66"
    assert clientip.client_ip("203.0.113.66", "6.6.6.6, 7.7.7.7") == "203.0.113.66"
    assert clientip.peer_is_trusted("203.0.113.66") is False


def test_empty_trusted_list_never_reads_headers(monkeypatch):
    """受信列表为空 = 一个代理头都不采信。"""
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies([]))
    assert clientip.client_ip("127.0.0.1", "6.6.6.6") == "127.0.0.1"


def test_cf_connecting_ip_ignored_from_untrusted_peer(client, monkeypatch):
    """不受信来源伪造 CF-Connecting-IP 也无效（只能靠受信代理头生效）。"""
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies(["127.0.0.1"]))
    r = client.get("/api/summary",
                   headers={"CF-Connecting-IP": "6.6.6.6", "X-Token": TEST_TOKEN})
    assert r.status_code == 200


# ====================================================================
# 4. config：HUB_PUBLIC 对监听地址的影响
# ====================================================================

def test_config_host_defaults_to_all_without_public():
    """未设 HUB_PUBLIC → HUB_HOST 仍是 0.0.0.0（局域网直连不变）。"""
    import json
    import os as _os

    env = dict(_os.environ)
    env.pop("HUB_PUBLIC", None)
    env["PYTHONPATH"] = str(SERVER_DIR)
    r = subprocess.run(
        [sys.executable, "-c",
         "import json,config;print(json.dumps({'host':config.HUB_HOST}))"],
        cwd=str(SERVER_DIR), env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["host"] == "0.0.0.0"


def test_config_host_defaults_to_loopback_with_public():
    """HUB_PUBLIC=1 → HUB_HOST 缺省收成 127.0.0.1。"""
    import json
    import os as _os

    env = dict(_os.environ)
    env["HUB_PUBLIC"] = "1"
    env.pop("HUB_HOST", None)
    env["PYTHONPATH"] = str(SERVER_DIR)
    r = subprocess.run(
        [sys.executable, "-c",
         "import json,config;print(json.dumps({'host':config.HUB_HOST,'public':config.HUB_PUBLIC}))"],
        cwd=str(SERVER_DIR), env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["public"] is True
    assert got["host"] == "127.0.0.1"


def test_explicit_host_wins_over_public_default():
    """显式设 HUB_HOST 时仍然优先（有人确实想让服务对内网也直连）。"""
    import json
    import os as _os

    env = dict(_os.environ)
    env["HUB_PUBLIC"] = "1"
    env["HUB_HOST"] = "0.0.0.0"
    env["PYTHONPATH"] = str(SERVER_DIR)
    r = subprocess.run(
        [sys.executable, "-c", "import json,config;print(json.dumps({'host':config.HUB_HOST}))"],
        cwd=str(SERVER_DIR), env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["host"] == "0.0.0.0"


# ====================================================================
# 5. 启动日志：五项参数都要能查到
# ====================================================================

def test_startup_log_lists_mode_and_switches(client, caplog):
    """启动日志必须含 模式/监听/UDP/豁免/受信代理 五项。

    服务化部署走 uvicorn main:app，`__main__` 块里的 print 一个都看不到，
    所以这五项必须能进 server.log。
    """
    import logging

    import main

    with caplog.at_level(logging.INFO, logger="hub.security"):
        main._log_security_mode()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "运行模式=" in text
    assert "UDP广播=" in text
    assert "回环免令牌豁免=" in text
    assert "受信代理=" in text
    assert "监听=" in text


def test_startup_log_warns_when_public_without_trusted_proxies(client, monkeypatch, caplog):
    """公网模式 + 受信列表为空 → 必须告警（限流会把整个隧道算一个 IP）。"""
    import logging

    import clientip
    import main

    monkeypatch.setattr(main, "HUB_PUBLIC", True)
    monkeypatch.setattr(clientip, "TRUSTED", clientip.TrustedProxies([]))
    with caplog.at_level(logging.INFO, logger="hub.security"):
        main._log_security_mode()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "HUB_TRUSTED_PROXIES 为空" in text


def test_startup_log_warns_when_public_with_bypass(client, monkeypatch, caplog):
    """公网模式 + 回环豁免开着 → 必须告警（等于对公网开放无鉴权访问）。"""
    import logging

    import main

    monkeypatch.setattr(main, "HUB_PUBLIC", True)
    monkeypatch.setattr(publicmode, "local_bypass_enabled", lambda *a, **k: True)
    with caplog.at_level(logging.INFO, logger="hub.security"):
        main._log_security_mode()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "回环免令牌豁免已开" in text