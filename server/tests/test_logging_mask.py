"""访问日志脱敏测试（M1a-D）。

三层验证：
1. 纯函数 `mask_query` 的行为（含边界：多个参数、大小写、无 query）；
2. `SensitiveQueryFilter` 作用在 LogRecord 上——**重点是 record.args**，
   因为 uvicorn 的 access 日志把 URL 放在 args 里而不是 msg 里；
3. 端到端：真起一个 uvicorn（线程内 + 临时日志文件），发一个带 `?token=` 的请求，
   读日志文件断言只剩 `token=***`、明文不出现。
"""
import logging
import re
import threading
import time

import httpx
import pytest

from logging_setup import SensitiveQueryFilter, build_log_config, mask_query

PLAINTEXT = "SUPER-SECRET-TOKEN-9f3ac1"


# ---------------- 纯函数 ----------------

@pytest.mark.parametrize("raw,expected", [
    ("/api/diary?token=abc123", "/api/diary?token=***"),
    ("/api/x?token=abc&sig=zzz", "/api/x?token=***&sig=***"),
    ("/api/x?sig=zzz&token=abc", "/api/x?sig=***&token=***"),
    ("/api/x?TOKEN=AbC", "/api/x?TOKEN=***"),
    ("/api/x?date=2026-10-20", "/api/x?date=2026-10-20"),          # 普通参数不动
    ("/api/x", "/api/x"),                                          # 无 query 不动
    ("", ""),
    ("token=abc", "token=***"),                                    # 无 ? 前缀也打码（兜底）
])
def test_mask_query(raw, expected):
    assert mask_query(raw) == expected


def test_mask_query_idempotent():
    once = mask_query("/api/x?token=abc&sig=zzz")
    assert mask_query(once) == once


# ---------------- Filter 作用在 record 上 ----------------

def _record(msg, args):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, msg, args, None)


def test_filter_masks_args_not_msg():
    """uvicorn 的 access 日志形如 info('%s - "%s" %d', addr, request_line, status)，
    URL 在 args[1]，只改 msg 的过滤器会漏掉它。"""
    rec = _record('%s - "%s" %d', ("10.0.0.9:5555", f"GET /api/hub/netinfo?token={PLAINTEXT} HTTP/1.1", 200))
    assert SensitiveQueryFilter().filter(rec) is True
    out = rec.getMessage()
    assert "token=***" in out
    assert PLAINTEXT not in out
    assert "10.0.0.9:5555" in out and "200" in out       # 其它信息不能丢


def test_filter_handles_dict_args():
    """logging 会把单元素 mapping 的 args 解包成 dict，过滤器必须认这种形态。"""
    rec = _record("%(url)s", ({"url": f"/api/x?token={PLAINTEXT}"},))
    SensitiveQueryFilter().filter(rec)
    assert PLAINTEXT not in rec.getMessage()
    assert "token=***" in rec.getMessage()


def test_filter_masks_non_str_args_via_final_message():
    """兜底：URL 以非 str 对象进 args（httpx 传的是 httpx.URL）时，
    第 1 步按 isinstance(str) 拦不住，必须靠格式化后的整条消息兜住。"""
    class FakeURL:                      # 模拟 httpx.URL：不是 str，但 str() 后含令牌
        def __str__(self):
            return f"http://127.0.0.1:8637/api/hub/netinfo?token={PLAINTEXT}"

    rec = _record("HTTP Request: %s %s", ("GET", FakeURL()))
    SensitiveQueryFilter().filter(rec)
    assert PLAINTEXT not in rec.getMessage()
    assert "token=***" in rec.getMessage()


def test_filter_keeps_non_string_args():
    rec = _record("%s %d", ("/api/x?token=abc", 200))
    SensitiveQueryFilter().filter(rec)
    assert rec.getMessage() == "/api/x?token=*** 200"


# ---------------- 端到端：真起 uvicorn ----------------

def test_http_client_bypasses_proxy_env(monkeypatch):
    """回归锁：NO_PROXY 写成 "[::1]" 时，trust_env=True 会在 build_request 阶段抛
    httpx.InvalidURL: Invalid port ':1]'（实测踩过）。E2E 用 trust_env=False 绕过。

    这条断言同时记录"为什么会炸"，避免以后有人把 trust_env=False 删回去。
    """
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "[::1],127.0.0.1,localhost")

    with pytest.raises(httpx.InvalidURL):
        httpx.Client(trust_env=True, timeout=5).build_request("GET", "http://127.0.0.1:9/x")

    client = httpx.Client(trust_env=False, timeout=5)
    req = client.build_request("GET", "http://127.0.0.1:9/x?token=abc")
    assert "token=abc" in str(req.url)
    assert not client._mounts, "trust_env=False 时不该挂任何代理 transport"


def test_real_access_log_is_masked(tmp_path):
    """起一个真 uvicorn（线程内，日志写临时文件），发带 token 的请求，读文件断言。"""
    import uvicorn

    from main import app

    log_file = tmp_path / "access.log"
    cfg = build_log_config(log_file)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_config=cfg, log_level="info")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    try:
        for _ in range(200):                     # 等 started + 拿到实际端口
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "uvicorn 未在预期时间内启动"
        port = server.servers[0].sockets[0].getsockname()[1]

        # netinfo 在免鉴权白名单里，因此 query 上的 token 会被原样带进 access log。
        # trust_env=False：本机测试不该读 HTTP(S)_PROXY / NO_PROXY——实测某些环境的
        # NO_PROXY 写成 "[::1]" 时，httpx 会把它当代理规则解析出 Invalid port ':1]'。
        with httpx.Client(trust_env=False, timeout=10) as http:
            r = http.get(f"http://127.0.0.1:{port}/api/hub/netinfo?token={PLAINTEXT}")
        assert r.status_code == 200, r.text

        text = ""
        for _ in range(100):                     # 等日志落盘（RotatingFileHandler 每次 emit 都 flush）
            if log_file.exists():
                text = log_file.read_text(encoding="utf-8")
                if "token=***" in text:
                    break
            time.sleep(0.05)
    finally:
        server.should_exit = True
        t.join(timeout=10)

    assert "token=***" in text, f"日志里没找到打码后的 query：\n{text}"
    assert PLAINTEXT not in text, f"明文令牌泄漏到日志：\n{text}"
    # 打码那一行应该长这样，且方法/路径/状态码都还在
    masked_line = next(ln for ln in text.splitlines() if "token=***" in ln)
    assert re.search(r'"GET /api/hub/netinfo\?token=\*\*\* HTTP/1\.1" 200', masked_line), masked_line


def test_build_log_config_keeps_previous_shape():
    """除新增 filters 外，配置项必须和改前一致（文件名/轮转/格式/级别）。"""
    cfg = build_log_config(__import__("pathlib").Path("x.log"))
    h = cfg["handlers"]["h"]
    assert cfg["root"] == {"level": "INFO", "handlers": ["h"]}
    assert cfg["formatters"]["f"]["format"] == "%(asctime)s %(levelname)s %(message)s"
    assert h["class"] == "logging.handlers.RotatingFileHandler"
    assert h["maxBytes"] == 2 * 1024 * 1024 and h["backupCount"] == 2
    assert h["encoding"] == "utf-8"
    assert cfg["disable_existing_loggers"] is False


# ---------------- 外部 log_config 场景 ----------------

def test_install_access_log_filter_survives_external_log_config(tmp_path):
    """模拟 `uvicorn main:app`：外部 dictConfig 重新定义 uvicorn.access
    （自带 handler、propagate=False），过滤器必须仍然生效。

    这正是 install_access_log_filter 存在的理由——那种启动方式下
    build_log_config 根本不参与。
    """
    import logging.config

    from logging_setup import install_access_log_filter

    log_file = tmp_path / "external.log"
    external_cfg = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"access": {"format": "%(levelname)s %(message)s"}},
        "handlers": {
            "h": {
                "class": "logging.FileHandler",
                "filename": str(log_file),
                "encoding": "utf-8",
                "formatter": "access",
            }
        },
        "loggers": {
            # 形状照抄 uvicorn 默认 LOGGING_CONFIG 的 uvicorn.access：无 filters 键
            "uvicorn.access": {"handlers": ["h"], "level": "INFO", "propagate": False},
        },
    }

    lg = logging.getLogger("uvicorn.access")
    install_access_log_filter()
    assert any(isinstance(f, SensitiveQueryFilter) for f in lg.filters)
    n_before = sum(isinstance(f, SensitiveQueryFilter) for f in lg.filters)
    install_access_log_filter()                       # 重复调用不该重复挂
    assert sum(isinstance(f, SensitiveQueryFilter) for f in lg.filters) == n_before

    logging.config.dictConfig(external_cfg)           # 外部配置后置，过滤器要活下来
    assert any(isinstance(f, SensitiveQueryFilter) for f in lg.filters), (
        "外部 dictConfig 把过滤器清掉了，uvicorn main:app 会漏"
    )

    # 调用方式与 uvicorn 一致：三个独立位置参数（写成单个 tuple 会被 logging
    # 当成一层嵌套，format 阶段直接 TypeError，与脱敏无关）
    lg.info(
        '%s - "%s" %d',
        "10.0.0.9:5555",
        f"GET /api/hub/netinfo?token={PLAINTEXT} HTTP/1.1",
        200,
    )

    text = log_file.read_text(encoding="utf-8")
    assert "token=***" in text, text
    assert PLAINTEXT not in text, f"外部 log_config 下明文泄漏：\n{text}"


def test_main_installs_filter_on_import():
    """main 一旦被 import，uvicorn.access 上就该有过滤器（不等 __main__ 分支）。"""
    import main  # noqa: F401  （导入即触发 install）
    from logging_setup import SensitiveQueryFilter

    lg = logging.getLogger("uvicorn.access")
    assert any(isinstance(f, SensitiveQueryFilter) for f in lg.filters), (
        "import main 时必须已挂上脱敏过滤器，否则 uvicorn main:app 会漏"
    )
