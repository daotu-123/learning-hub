# -*- coding: utf-8 -*-
"""PyInstaller runtime hook：把 stdout / stderr 固定为 UTF-8。

**为什么需要这个 hook**（而不是靠环境变量）：

`PYTHONIOENCODING=utf-8` 与 `PYTHONUTF8=1` 对 **frozen exe 均无效**——
已实测三种环境（不设 / PYTHONIOENCODING / PYTHONUTF8）输出字节完全相同，
都是 cp936。PyInstaller 的 bootloader 在解释器初始化前就接管了标准流，
环境变量来不及生效。因此只能在解释器起来之后由 runtime hook 重新配置。

**不修的后果不只是乱码**：本服务端大量使用中文 `print()`
（manage.py 的全部提示、main.py 启动横幅、NO_ACCOUNT_MESSAGE 等）。
标准流编码跟随控制台代码页，一旦服务跑在非中文 Windows（或代码页被改成
65001/1252）上，`print("目标数据目录：…")` 会直接抛
`UnicodeEncodeError` —— main.py 的 `_startup()` 里就有一句带 flush 的
中文 print，那会让**整个服务起不来**，而现象是"启动即退出、没有任何日志"。
固定成 UTF-8 后，输出与运行机器的区域设置彻底解耦。

代价：日志文件变成 UTF-8。中文 Windows 的记事本默认按 ANSI(cp936)打开会
显示乱码——用 VS Code 或把记事本改成 UTF-8 即可。两害相权，选"永不崩"。

runtime hook 在入口脚本之前执行，因此对 main.py / manage.py 都生效。
"""
import sys


def _force_utf8(stream) -> None:
    """reconfigure 只在 TextIOWrapper 上存在；stream 为 None 时直接跳过。"""
    if stream is None:
        return
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except Exception:
        # 配置失败不致命：退回到系统默认编码，至少服务还能起来
        pass


for _s in (sys.stdout, sys.stderr):
    _force_utf8(_s)
