# -*- coding: utf-8 -*-
"""标准流编码兜底（M3-P0）。

## 问题

中文 Windows 上，当 stdout/stderr 是**重定向**的普通文件或管道时
（计划任务、NSSM、`> log.txt`、`| tee`、CI），Python 用 **locale 编码**
（cp936 / GBK）而不是控制台的 UTF-8。GBK 里没有这些字符：

    ⚠ (U+26A0)   ✖ (U+2716)   ─ │ ┌ └   ➜ 等制表符与方块

而本项目的中文输出里到处都是它们。于是：

    python main.py
    print("  ⚠ 回环免令牌豁免: …")
    → UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0'
    → 退出码 1，**服务根本没起来**，日志里只剩一行堆栈

实测就是这样崩的（2026-10-21，干净 env + stdout 重定向到文件）。

## 为什么不能靠环境变量

`PYTHONIOENCODING` / `PYTHONUTF8` 必须在**进程启动前**设好，服务已经跑起来
就来不及；而服务化部署（任务计划程序、NSSM）通常不会去设它。
P1-1 还实测出更糟的一点：对打包 exe 这两个变量**都无效**——
PyInstaller 的 bootloader 在解释器初始化之前就接管了标准流。

所以只能在解释器里、第一条 print 之前自己 `reconfigure`。

## 为什么 errors="replace"

默认是 `strict`，遇到不可编码字符直接抛异常。
这里显式用 `replace`：即便 reconfigure 本身失败、编码仍是 GBK，
后续 print 也只会把那个字符变成 `?`，而**不是把服务打挂**。
启动横幅是给人看的，不值得为它退出。

## 为什么单独一个模块而不是放 main.py

`manage.py` 需要同一份逻辑。若 manage 直接 `from main import ...`，
会因为 import main 而构建整个 FastAPI app 并 `mkdir` 数据目录——
对管理 CLI 是意外副作用（它正要拒绝在数据目录不明确时写入，
却又顺手把那个目录建出来）。而复制一份则必然漂移：
一个加了 `errors="replace"`、另一个没加，就是最难查的那种不一致。
"""
import sys


def force_utf8_stdio() -> None:
    """把 stdout/stderr 固定成 UTF-8，尽最大努力，失败也不抛。

    - 流为 None（pythonw / GUI 子系统）→ 跳过
    - 不是 TextIOWrapper（没有 reconfigure）→ 跳过
    - reconfigure 抛任何异常 → 吞掉

    最后一条是重点：**修编码这件事本身绝不能成为新的崩溃源**。
    """
    for _name in ("stdout", "stderr"):
        stream = getattr(sys, _name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def stdio_is_utf8() -> bool:
    """stdout/stderr 当前是不是 UTF-8。测试与排障用。

    返回 False 的三种情况：流不存在、没有 reconfigure、或者编码不是 utf-8。
    注意它只报告**当前状态**，不尝试修复。
    """
    for _name in ("stdout", "stderr"):
        stream = getattr(sys, _name, None)
        if stream is None:
            return False
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc not in ("utf8", "utf8sig"):
            return False
    return True