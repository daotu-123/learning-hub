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

M2c 新增：
    HUB_API_LIMIT_PER_MIN    全局 API 限流（每分钟）   默认 120
    HUB_API_BURST            全局 API 突发容量          默认 60
    HUB_UPLOAD_LIMIT_PER_MIN 上传类限频（每分钟）      默认 12
    HUB_UPLOAD_BURST         上传类突发容量             默认 4
    HUB_LOGIN_MAX_FAILURES   连续失败几次后开始退避    默认 5
    HUB_LOGIN_BASE_DELAY     第一次退避秒数            默认 1
    HUB_LOGIN_MAX_DELAY      退避封顶秒数              默认 60
    HUB_LOGIN_WINDOW         "连续失败"窗口秒数        默认 900
    HUB_TRUSTED_PROXIES      受信反代 IP/CIDR（逗号分隔）默认空 = 不采信 XFF
"""
import os
import sys
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
#
# 缺省值分两种情况，**只有打包运行时不同**：
#   源码运行  <HUB_ROOT>\server\data          （历史行为，逐字不变）
#   打包运行  <exe 所在目录>\data
#
# 为什么打包时要另算：HUB_ROOT 的缺省值是开发机路径 E:\agent\androd-app，
# 这个字符串会被原样打进 exe。部署机上它不存在，于是 sqlite3.connect
# 报一个看不懂的错；更糟的是若部署机上恰好有同名路径，账号会被**悄悄**
# 写进去——本轮实测踩到：不带 HUB_DATA_DIR 跑 LearningHubManage.exe，
# 账号写进了开发机的 server/data/account.json。
# 其它 HUB_ROOT 派生路径（hub_web / web_dist）都有"不存在就回退到
# sys._MEIPASS"的判断，唯独 DATA_DIR 没有（它是要被创建的目标，
# 没法用存在性判断），所以必须在这里显式处理。
def _default_data_dir() -> str:
    if getattr(sys, "frozen", False):
        try:
            return str(Path(sys.executable).resolve().parent / "data")
        except OSError:
            return "data"
    return str(HUB_ROOT / "server" / "data")


DATA_DIR = _env_path("HUB_DATA_DIR", _default_data_dir())
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

# ---------------------------------------------------------------- M2c 限流阈值
# 全部是**建议值**，缺省即上方 ratelimit 模块里的常量。
# 单账号自用的量级；如果将来放开多人使用，这几个数必须重新标定。
HUB_API_LIMIT_PER_MIN = _env_int("HUB_API_LIMIT_PER_MIN", "120")      # 全局令牌桶速率
HUB_API_BURST = _env_int("HUB_API_BURST", "60")                        # 全局桶容量（突发）
HUB_UPLOAD_LIMIT_PER_MIN = _env_int("HUB_UPLOAD_LIMIT_PER_MIN", "12")  # 上传类限频
HUB_UPLOAD_BURST = _env_int("HUB_UPLOAD_BURST", "4")
HUB_LOGIN_MAX_FAILURES = _env_int("HUB_LOGIN_MAX_FAILURES", "5")      # 连续失败几次后退避
HUB_LOGIN_BASE_DELAY = float(_env("HUB_LOGIN_BASE_DELAY", "1"))        # 第一次退避 1s
HUB_LOGIN_MAX_DELAY = float(_env("HUB_LOGIN_MAX_DELAY", "60"))         # 退避封顶 60s
HUB_LOGIN_WINDOW = float(_env("HUB_LOGIN_WINDOW", "900"))              # "连续"窗口 15 分钟

# 受信反向代理（HUB_TRUSTED_PROXIES）：逗号分隔的 IP 或 CIDR。
# **默认为空 = 不采信任何 X-Forwarded-For**。
# 部署在 Caddy/Nginx 后面时必须显式配上，否则限流会把整个代理当成一个 IP。
HUB_TRUSTED_PROXIES = [x.strip() for x in _env("HUB_TRUSTED_PROXIES", "").split(",") if x.strip()]
