"""配置化回归测试（M1a）。

锁定两件事：
1. **默认值逐字等于历史硬编码** —— 不设任何环境变量时，行为不许变；
2. **三处 vault 硬编码已收敛到同一来源** —— 防止有人再复制一份路径进去。

环境变量覆盖用例跑在子进程里：直接 reload config 会污染当前进程的模块状态，
进而影响同会话其它测试。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent

# 改动前的硬编码值（git 历史可查），逐个对照
HARDCODED = {
    "host": "0.0.0.0",
    "port": "8637",
    "root": r"E:\agent\androd-app",
    "vault": r"E:\soft_files\obsidian-files\self-improve\self-improve",
    "favorites": r"E:\soft_files\obsidian-files\depot\class",
    "hermes": r"E:\soft_files\tools\hermes-scripts",
    "deeptutor": r"D:\record\deeptutor\data\user",
    "data": r"E:\agent\androd-app\server\data",
    "udp_port": "8638",
}


def _config_env(extra: dict) -> dict:
    """子进程里加载 config 并 dump 关键值，避免污染当前进程。"""
    code = (
        "import json,os;"
        + "".join(f"os.environ[{k!r}]={v!r};" for k, v in extra.items())
        + "import config;"
        "print(json.dumps({'host':config.HUB_HOST,'port':config.HUB_PORT,"
        "'root':str(config.HUB_ROOT),'vault':str(config.OBSIDIAN_VAULT),"
        "'fav':str(config.FAVORITES_ROOT),'hermes':str(config.HERMES_DIR),"
        "'deeptutor':str(config.DEEPTUTOR_DIR),'data':str(config.DATA_DIR),"
        "'udp':config.UDP_PORT,'token':config.HUB_AUTH_TOKEN}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=str(SERVER_DIR), check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


# ---------------- 默认值 = 历史硬编码 ----------------

def test_defaults_equal_hardcoded():
    import config

    assert config.HUB_HOST == HARDCODED["host"]
    assert config.HUB_PORT == int(HARDCODED["port"])
    assert str(config.HUB_ROOT) == HARDCODED["root"]
    assert str(config.OBSIDIAN_VAULT) == HARDCODED["vault"]
    assert str(config.FAVORITES_ROOT) == HARDCODED["favorites"]
    assert str(config.HERMES_DIR) == HARDCODED["hermes"]
    assert str(config.DEEPTUTOR_DIR) == HARDCODED["deeptutor"]
    assert str(config.DATA_DIR) == HARDCODED["data"]
    assert config.UDP_PORT == int(HARDCODED["udp_port"])
    assert config.HUB_AUTH_TOKEN == ""      # 空 = 沿用 settings.json 惰性生成


def test_defaults_unchanged_with_clean_env():
    """显式清空相关环境变量后再加载一遍，确认没有隐性依赖。"""
    clean = {k: "" for k in (
        "HUB_HOST", "HUB_PORT", "HUB_ROOT", "HUB_VAULT", "HUB_FAVORITES",
        "HUB_HERMES_DIR", "HUB_DEEPTUTOR_DIR", "HUB_DATA_DIR", "HUB_UDP_PORT",
        "HUB_AUTH_TOKEN",
    )}
    got = _config_env(clean)
    assert got == {
        "host": HARDCODED["host"],
        "port": int(HARDCODED["port"]),
        "root": HARDCODED["root"],
        "vault": HARDCODED["vault"],
        "fav": HARDCODED["favorites"],
        "hermes": HARDCODED["hermes"],
        "deeptutor": HARDCODED["deeptutor"],
        "data": HARDCODED["data"],
        "udp": int(HARDCODED["udp_port"]),
        "token": "",
    }


# ---------------- 三处 vault 同源 ----------------

def test_vault_single_source():
    """main / vault_reader / openmaic 必须共用同一个 vault 根对象。"""
    import config
    import main
    import hub.openmaic as om
    import hub.vault_reader as vr

    assert main.OBSIDIAN_VAULT is config.OBSIDIAN_VAULT
    assert vr.OBSIDIAN_VAULT is config.OBSIDIAN_VAULT
    # openmaic 的 roots 是 JSON 配置（字符串），比对值而不是对象 identity
    assert str(om.DEFAULT_CFG["roots"][0]) == str(config.OBSIDIAN_VAULT)


def test_favorites_single_source():
    import config
    import main
    import hub.vault_reader as vr

    assert vr.CLASS_DIR is config.FAVORITES_ROOT
    assert main.XHS_DIR == config.FAVORITES_ROOT / "小红书收藏"


def test_data_dir_single_source():
    import config
    import hub.openmaic as om
    import hub.router as r
    import hub.writer as wr
    import main

    assert main.DATA_DIR is config.DATA_DIR
    assert r.DATA_DIR is config.DATA_DIR
    assert wr.DATA_DIR is config.DATA_DIR
    assert om.DATA_DIR is config.DATA_DIR


def test_port_single_source():
    import config
    import hub.router as r
    import main

    assert main.SERVER_PORT == config.HUB_PORT
    assert r.HUB_PORT == config.HUB_PORT


def test_hermes_dir_single_source():
    """vault_reader 与 queue_reader 必须共用同一个 hermes 目录对象。"""
    import config
    import hub.queue_reader as qr
    import hub.vault_reader as vr

    assert vr.HERMES_SCRIPTS is config.HERMES_DIR
    assert qr.HERMES_SCRIPTS is config.HERMES_DIR


def test_deeptutor_paths_derive_from_config():
    import config
    import main

    assert main.DEEPTUTOR_DB == config.DEEPTUTOR_DIR / "chat_history.db"
    assert main.DEEPTUTOR_LOG == config.DEEPTUTOR_DIR / "logs" / "deeptutor.jsonl"


def test_udp_port_from_config():
    import config
    import main
    import inspect

    src = inspect.getsource(main)
    assert "UDP_PORT" in src, "UDP 广播应使用 config.UDP_PORT，不该再写死 8638"
    assert "255.255.255.255\", 8638)" not in src
    assert config.UDP_PORT == 8638


# ---------------- 环境变量覆盖 ----------------

def test_env_overrides():
    got = _config_env({
        "HUB_HOST": "127.0.0.1",
        "HUB_PORT": "8641",
        "HUB_ROOT": r"D:\deploy\hub",
        "HUB_VAULT": r"D:\tmp\vault",
        "HUB_FAVORITES": r"D:\tmp\fav",
        "HUB_HERMES_DIR": r"D:\tmp\hermes",
        "HUB_DEEPTUTOR_DIR": r"D:\tmp\deeptutor",
        "HUB_DATA_DIR": r"D:\tmp\data",
        "HUB_UDP_PORT": "9999",
        "HUB_AUTH_TOKEN": "tok-from-env",
    })
    assert got["host"] == "127.0.0.1"
    assert got["port"] == 8641
    assert got["root"] == r"D:\deploy\hub"
    assert got["vault"] == r"D:\tmp\vault"
    assert got["fav"] == r"D:\tmp\fav"
    assert got["hermes"] == r"D:\tmp\hermes"
    assert got["deeptutor"] == r"D:\tmp\deeptutor"
    assert got["data"] == r"D:\tmp\data"
    assert got["udp"] == 9999
    assert got["token"] == "tok-from-env"


def test_blank_env_falls_back_to_default():
    """空串 / 纯空白视为未设置，不能把端口变成空串。"""
    got = _config_env({"HUB_PORT": "   ", "HUB_VAULT": "", "HUB_ROOT": " "})
    assert got["port"] == 8637
    assert got["vault"] == HARDCODED["vault"]
    assert got["root"] == HARDCODED["root"]


def test_hub_root_drives_data_dir_default():
    """VPS 场景：只设 HUB_ROOT，data 目录要跟着走（DATA_DIR 缺省值由 HUB_ROOT 派生）。"""
    got = _config_env({"HUB_ROOT": r"D:\deploy\hub"})
    assert got["root"] == r"D:\deploy\hub"
    assert got["data"] == r"D:\deploy\hub\server\data"


def test_bad_port_raises_instead_of_silently_defaulting():
    """端口写错必须炸，不能静默回落到 8637（否则"改端口没生效"极难排查）。"""
    with pytest.raises(subprocess.CalledProcessError):
        _config_env({"HUB_PORT": "not-a-number"})


# ---------------- 令牌来源链 ----------------

def test_auth_token_prefers_workbench_env(monkeypatch):
    """既有 WORKBENCH_AUTH_TOKEN 优先级不许被 HUB_AUTH_TOKEN 抢走。"""
    import main

    monkeypatch.setenv("WORKBENCH_AUTH_TOKEN", "from-workbench")
    monkeypatch.setattr(main, "HUB_AUTH_TOKEN", "from-hub")
    assert main.auth_token() == "from-workbench"


def test_auth_token_uses_hub_env_when_workbench_absent(monkeypatch):
    import main

    monkeypatch.delenv("WORKBENCH_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "HUB_AUTH_TOKEN", "from-hub")
    assert main.auth_token() == "from-hub"


def test_auth_token_generates_and_persists_when_no_env(monkeypatch):
    """两级 env 都空 → 读 settings.json → 没有再生成并写回（stub 掉写盘，不碰真实数据）。"""
    import main

    monkeypatch.delenv("WORKBENCH_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "HUB_AUTH_TOKEN", "")
    monkeypatch.setattr(main, "get_settings", lambda: {})
    written = {}
    monkeypatch.setattr(main, "save_settings", lambda patch: written.update(patch) or patch)

    tok = main.auth_token()
    assert tok, "缺省链路必须能生成令牌"
    assert written.get("auth_token") == tok, "生成的令牌必须走既有写回逻辑"
