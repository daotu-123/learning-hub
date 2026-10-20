"""pytest 共享配置。

鉴权中间件要求「非回环请求必须带令牌」。TestClient 的默认来源是 testclient
（非回环），所以所有测试都必须带令牌。这里在导入 main 之前把令牌固定下来，
避免测试依赖随机生成的 settings.json。
"""
import os

import pytest

TEST_TOKEN = "test-token-for-pytest-only"

# 必须在 import main 之前设置：auth_token() 优先读环境变量
os.environ["WORKBENCH_AUTH_TOKEN"] = TEST_TOKEN

# ---------------------------------------------------------------- M2a 身份体系共用夹具
# 模拟同网段设备（非回环）与本机（回环）
LAN = ("192.168.1.50", 51234)
LOOP = ("127.0.0.1", 51234)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把账号/会话文件指到临时目录，**绝不碰真实数据目录**。

    M2a 的账号文件（account.json）与会话文件（sessions.json）都落在
    server/data/ 下；测试必须指向临时目录，否则会在真实目录里建出账号。
    """
    import auth_sessions

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(auth_sessions, "ACCOUNT_JSON", data / "account.json")
    monkeypatch.setattr(auth_sessions, "SESSIONS_JSON", data / "sessions.json")
    return data


def leaks(text, secret) -> bool:
    """text 里是否含 secret。

    刻意做成函数而不是让测试写 `assert SECRET not in text`：
    后者在断言失败时会被 pytest 展开成 `assert '真实口令' not in '...'`，
    等于把口令/令牌打印进 CI 日志。用函数形式，失败时只显示
    `assert not leaks(...)`，不会展开参数。
    """
    return secret in text
