# -*- coding: utf-8 -*-
"""所有模块可导入回归测试（M1b-P0）。

为什么需要这条测试：
M1b-2 拆 routers/ 时，main.py 顶层的 `import socket / sys / time / uvicorn`
被一并清掉。这 4 个名字只在 `if __name__ == "__main__":` 块及其派生的线程函数
（UDP 广播 loop、_open_browser）里被用到，于是出现了这种局面：

    `import main`        -> 全绿
    TestClient 全套用例  -> 全绿
    `python main.py`     -> NameError 崩溃

而 `python main.py` 恰恰是 start_hub.bat 与 PyInstaller 打包用的真实入口。

本测试把「server 下每个模块都能被 import」固化下来，防止后续搬动代码时漏掉依赖。
注意它**兜不住** `__main__` 块内部的漏 import（import 时那段代码不执行）——
那一块由 tests/test_startup_smoke.py 负责。
"""
import importlib
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

# 构建期脚本：依赖 Pillow，本机 PIL 二进制损坏，与运行时无关，故排除
EXCLUDED = {"make_icon"}

# 期望可导入的全部模块。新增模块必须同步加到这里（否则下面那条穷尽性断言会失败）。
EXPECTED_MODULES = [
    # 顶层共享模块
    "common",
    "config",
    "health",
    "errors",
    "logging_setup",
    "apiv1",
    "auth_sessions",
    "ratelimit",
    "clientip",
    "media_sign",
    "security_headers",
    "usage_db",
    "publicmode",
    "stdiosafe",
    "manage",
    "dump_routes",
    # PyInstaller runtime hook：在入口脚本之前执行，改 stdout/stderr 的编码
    # 并按需 tee 到文件。它是打包链路的一环，同样必须可导入。
    "pyi_rth_utf8_io",
    "main",
    # routers/ 十个业务域
    "routers",
    "routers.auth",
    "routers.static_pages",
    "routers.tasks",
    "routers.legacy_life",
    "routers.docs",
    "routers.favorites",
    "routers.usage",
    "routers.pomodoro",
    "routers.settings",
    "routers.media",
    "routers.ai",
    # hub/
    "hub",
    "hub.router",
    "hub.openmaic",
    "hub.queue_reader",
    "hub.vault_reader",
    "hub.writer",
]


def _discover() -> set:
    """扫描 server/、server/routers/、server/hub/ 下的全部 .py，换算成模块名。"""
    found = set()
    for p in SERVER_DIR.glob("*.py"):
        found.add(p.stem)
    for sub in ("routers", "hub"):
        for p in (SERVER_DIR / sub).glob("*.py"):
            found.add(sub if p.stem == "__init__" else "%s.%s" % (sub, p.stem))
    return found


def test_module_list_is_exhaustive():
    """清单必须与磁盘上的文件一一对应，防止新模块静默漏测。"""
    found = _discover() - EXCLUDED
    missing = sorted(found - set(EXPECTED_MODULES))
    stale = sorted(set(EXPECTED_MODULES) - found)
    assert not missing, "磁盘上有模块未加入可导入清单: %s" % missing
    assert not stale, "清单里有磁盘上不存在的模块: %s" % stale


@pytest.mark.parametrize("name", EXPECTED_MODULES)
def test_module_imports(name):
    """逐个 import：任何漏掉的依赖（NameError/ImportError）都会在这里炸出来。"""
    mod = importlib.import_module(name)
    assert mod is not None
