# -*- coding: utf-8 -*-
"""服务端配置（M1a 配置化）。

环境变量驱动，缺省值 = 历史硬编码值：不设任何环境变量时，行为与改前逐字一致。

设计约束：
1. 所有默认值都必须能在 git 历史里找到对应硬编码，禁止"顺手改默认值"。
2. 业务模块只 import 本模块，不再各自硬编码路径（vault 根曾 3 处重复）。
3. PROJECT_ROOT 保留绝对路径而不用 Path(__file__)：PyInstaller 打包运行时
   __file__ 指向包内临时目录，改用它会改变数据落点。

新增环境变量清单：
    HUB_HOST          监听地址            默认 0.0.0.0
    HUB_PORT          监听端口            默认 8637
    HUB_ROOT          项目根              默认 E:\\agent\\androd-app
    HUB_VAULT         Obsidian 主 vault   默认 E:\\soft_files\\obsidian-files\\self-improve\\self-improve
    HUB_FAVORITES     收藏库 vault        默认 E:\\soft_files\\obsidian-files\\depot\\class
    HUB_HERMES_DIR    hermes 账本目录     默认 E:\\soft_files\\tools\\hermes-scripts
    HUB_DEEPTUTOR_DIR DeepTutor 数据目录  默认 D:\\record\\deeptutor\\data\\user
    HUB_DATA_DIR      数据目录            默认 <HUB_ROOT>\\server\\data
    HUB_UDP_PORT      UDP 发现广播端口    默认 8638
    HUB_AUTH_TOKEN   访问令牌（可选）     默认空 = 沿用 settings.json 惰性生成链路
"""
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    """读环境变量：空串/纯空白视为未设置，回落默认值。"""
    v = (os.environ.get(name) or "").strip()
    return v if v else default


def _env_path(name: str, default: str) -> Path:
    return Path(_env(name, default))


def _env_int(name: str, default: str) -> int:
    try:
        return int(_env(name, default))
    except ValueError:
        # 配置写错时不要静默换成默认端口（那会让"改端口没生效"变得极难排查）
        raise RuntimeError(f"环境变量 {name} 不是合法整数: {os.environ.get(name)!r}")


# ---------------------------------------------------------------- 项目根
# 原 main.py:30 的硬编码。VPS 上项目不会装在 E:\agent\androd-app，必须可覆盖。
HUB_ROOT = _env_path("HUB_ROOT", r"E:\agent\androd-app")
PROJECT_ROOT = HUB_ROOT          # 兼容旧名（main.py 里以 APP_ROOT 引用）

# ---------------------------------------------------------------- 监听地址
HUB_HOST = _env("HUB_HOST", "0.0.0.0")
HUB_PORT = _env_int("HUB_PORT", "8637")
UDP_PORT = _env_int("HUB_UDP_PORT", "8638")   # 原 main.py 里写死的广播目标端口

# ---------------------------------------------------------------- 数据落点
# 原 main.py:31 / hub/router.py:31 / hub/openmaic.py:33 / hub/writer.py:26
DATA_DIR = _env_path("HUB_DATA_DIR", str(HUB_ROOT / "server" / "data"))
USAGE_DB = DATA_DIR / "usage.db"     # 原 main.py:34 / hub/router.py:35

# ---------------------------------------------------------------- Obsidian vault
# 原 main.py:37、hub/vault_reader.py:16、hub/openmaic.py:42（三处重复 → 现在同一来源）
OBSIDIAN_VAULT = _env_path(
    "HUB_VAULT", r"E:\soft_files\obsidian-files\self-improve\self-improve"
)
# 原 main.py:39（XHS_DIR）、hub/vault_reader.py:19（CLASS_DIR）
FAVORITES_ROOT = _env_path("HUB_FAVORITES", r"E:\soft_files\obsidian-files\depot\class")

# ---------------------------------------------------------------- hermes 账本
# 原 hub/vault_reader.py:20、hub/queue_reader.py:16（两处重复）
HERMES_DIR = _env_path("HUB_HERMES_DIR", r"E:\soft_files\tools\hermes-scripts")

# ---------------------------------------------------------------- DeepTutor
# 原 main.py:50-51（chat_history.db 与 logs/deeptutor.jsonl）
DEEPTUTOR_DIR = _env_path("HUB_DEEPTUTOR_DIR", r"D:\record\deeptutor\data\user")

# ---------------------------------------------------------------- 访问令牌
# 空 = 不改动既有链路：WORKBENCH_AUTH_TOKEN → settings.json → 首次非回环请求时
# 惰性生成并写回 settings.json（见 main.auth_token）。来源顺序不许变。
HUB_AUTH_TOKEN = _env("HUB_AUTH_TOKEN", "")
