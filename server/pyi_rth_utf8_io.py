# -*- coding: utf-8 -*-
"""PyInstaller runtime hook：UTF-8 标准流 + （可选）stdout/stderr 落文件。

**为什么需要这个 hook**（而不是靠环境变量或包装进程）：

1) 编码：`PYTHONIOENCODING=utf-8` 与 `PYTHONUTF8=1` 对 **frozen exe 均无效**——
   已实测三种环境（不设 / PYTHONIOENCODING / PYTHONUTF8）输出字节完全相同，
   都是 cp936。PyInstaller 的 bootloader 在解释器初始化前就接管了标准流，
   环境变量来不及生效。而本服务端大量使用中文 `print()`
   （manage.py 全部提示、main.py 启动横幅、NO_ACCOUNT_MESSAGE），标准流编码
   跟随控制台代码页：一旦跑在非中文 Windows 上，启动横幅那句中文 print 会抛
   `UnicodeEncodeError` —— main.py 的 `_startup()` 里就有一句带 flush 的
   中文 print，那会让**整个服务起不来**，而现象是"启动即退出、没有任何日志"。

2) 落文件：Windows 服务（Session 0，无控制台）里，GUI/console 进程的
   stdout/stderr 都没有可读的去处。而这里恰好有两类信息只在标准流上：
       - 启动横幅（main.py `__main__` 块，含数据目录/端口/手机该填的地址）
       - logging 配置生效之前的早期崩溃（import 失败等）
   uvicorn 的 access/error 日志已经由 logging_setup 写进
   `<DATA_DIR>/server.log`，所以标准流只需补上面这两类。

   做法是 tee 而不是 `cmd /c "exe > log 2>&1"` 包装：后者会让 SCM 的
   STOP 控制发给 cmd.exe 而不是 exe，停服务时大概率留下占着端口的孤儿进程。

**开关**：设了环境变量 `HUB_SERVICE_LOG_DIR` 才落文件。不设则完全不影响
交互式/开发场景（不会在仓库里撒日志文件）。
"""
import os
import sys
from pathlib import Path

# 单个文件上限。超了就滚成 .1 重开。启动横幅 + 早期崩溃都是偶发内容，
# 稳态下这两个文件应该几乎是空的，5MB 已经非常宽松。
_MAX_BYTES = 5 * 1024 * 1024


class _Tee:
    """同时写给原始标准流和文件的转发器。

    只实现 write/flush 这类文本流最小接口。**刻意不实现 fileno()**：
    uvicorn 的有些路径会拿 stdout 的 fileno 去做 select/epoll，
    而文件的 fd 与"控制台是否还有数据"语义不符，硬返回一个 fd 比抛异常
    更难排查。这里选择抛 OSError，调用方（uvicorn）有自己的降级路径。
    """

    def __init__(self, original, path: Path):
        self._original = original
        self._path = path
        self._fh = None

    def _open(self):
        if self._fh is not None:
            return self._fh
        try:
            if self._path.exists() and self._path.stat().st_size > _MAX_BYTES:
                # 简单滚动：旧的让位成 .1，重新开一个
                try:
                    self._path.replace(self._path.with_suffix(self._path.suffix + ".1"))
                except OSError:
                    pass
            self._fh = open(self._path, "a", encoding="utf-8", errors="replace")
        except OSError:
            self._fh = False          # 打不开就放弃落文件，别影响主流程
        return self._fh

    def write(self, data):
        if self._original is not None:
            try:
                self._original.write(data)
            except Exception:
                pass
        fh = self._open()
        if fh:
            try:
                fh.write(data)
            except Exception:
                pass
        return len(data) if isinstance(data, str) else 0

    def flush(self):
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass
        fh = self._open()
        if fh:
            try:
                fh.flush()
            except Exception:
                pass

    def close(self):
        fh = self._fh
        self._fh = None
        if fh and fh is not True:
            try:
                fh.close()
            except Exception:
                pass

    @property
    def encoding(self):
        return "utf-8"

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("_Tee has no fileno (stdout is teed to a file)")


def _force_utf8(stream):
    """reconfigure 只在 TextIOWrapper 上存在；stream 为 None 时直接跳过。"""
    if stream is None:
        return None
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return stream
    try:
        reconfigure(encoding="utf-8")
    except Exception:
        # 配置失败不致命：退回到系统默认编码，至少服务还能起来
        pass
    return stream


# ---------------------------------------------------------------- 1. UTF-8
_out = _force_utf8(sys.stdout)
_err = _force_utf8(sys.stderr)

# ---------------------------------------------------------------- 2. 落文件
_log_dir = (os.environ.get("HUB_SERVICE_LOG_DIR") or "").strip()
if _log_dir:
    try:
        _d = Path(_log_dir).expanduser()
        _d.mkdir(parents=True, exist_ok=True)
        sys.stdout = _Tee(_out, _d / "service-stdout.log")
        sys.stderr = _Tee(_err, _d / "service-stderr.log")
    except Exception:
        # 日志目录建不出来不能阻止服务启动；保持原样即可
        pass
