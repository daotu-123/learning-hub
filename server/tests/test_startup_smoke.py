# -*- coding: utf-8 -*-
"""真实入口启动冒烟（M1b-P1）。

这条测试存在的唯一理由：**TestClient 永远发现不了 `__main__` 块的问题。**

背景：M1b-2 拆 routers/ 时清掉了 main.py 顶层的 `import socket / sys / time /
uvicorn`，这 4 个名字只在 `if __name__ == "__main__":` 块及其派生的线程函数里被
用到。于是：

    import main        -> 全绿
    TestClient 全套    -> 全绿
    python main.py     -> NameError 崩溃

而 `python main.py` 正是 start_hub.bat 与 PyInstaller 打包用的入口。

所以这里不用 TestClient，而是真的 Popen 一次 `python main.py`，等端口起来，再断言
`GET /` 的 `lan_ip` 非空——后者同时锁住"`__main__` 里先算 LAN_IP"这个行为
（用 `uvicorn main:app` 启动时 LAN_IP 是 None，那条路径不归这里管）。

两条断言缺一不可：
  - 只断言 lan_ip 不够。漏 `import time` 时，崩的是 UDP 广播那个 daemon 线程，
    uvicorn 照常起、接口照常 200，快乐路径全绿（我实测确认过）。
    所以还要断言「启动日志里没有 traceback」。
  - 只断言日志不够。漏 `import uvicorn` 才会让主进程真的起不来，这条靠就绪轮询。

环境无关性：
  - 端口：绑 0 取空闲端口，HUB_PORT / HUB_UDP_PORT 都换掉，不抢 8637 / 8638；
  - 代理：httpx 一律 trust_env=False，带 HTTP_PROXY / NO_PROXY 也能跑；
  - 弹窗：main.py 会在服务就绪后 webbrowser.open(...)（打包成无窗口 exe 时这是
    唯一可见反馈）。测试里绝不能真弹浏览器，见下面的 _BROWSER_STUB。
  - lan_ip：依赖「有一条出网路由」，哪怕上不了外网也行；完全没有路由的机器上
    find_lan_ip() 会返回 None，此时报错信息会直接指出来。
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent

STARTUP_TIMEOUT = 20.0

# webbrowser 替身。原理：把这个文件写进一个目录，再把目录塞到子进程 PYTHONPATH
# 的最前面 —— sys.path 顺序是「脚本目录 → PYTHONPATH → 标准库」，于是子进程里的
# `import webbrowser` 会先命中替身，真实的浏览器就不会被拉起来。
#
# 安全性：子进程里只有 main.py 的 _open_browser() 用 webbrowser，且只调 open()。
# （已确认 site-packages 里仅 click/_termui_impl.py 引用 webbrowser，且只在
#  不会被调用的 edit/launch 分支里。）所以这个极简替身足够，不影响其它依赖。
#
# 为什么不直接用 BROWSER 环境变量：实测过，webbrowser.get() 会把不带 %s 的值
# 当浏览器名走 _synthesize，注册出一个 GenericBrowser 但执行失败（返回 False），
# 随后 open() 继续尝试 windows-default → os.startfile → 真实浏览器照样弹窗。
_BROWSER_STUB = '''\
# -*- coding: utf-8 -*-
"""测试替身：替换标准库 webbrowser，阻止真的弹出浏览器窗口。仅测试用。"""
import os
import pathlib


class Error(Exception):
    pass


def open(url, new=0, autoraise=True):
    log = os.environ.get("HUB_SMOKE_BROWSER_LOG")
    if log:
        try:
            pathlib.Path(log).write_text(url, encoding="utf-8")
        except Exception:
            pass
    return True


def open_new(url):
    return open(url, 1)


def open_new_tab(url):
    return open(url, 2)


def get(using=None):
    return None


def register(*_args, **_kwargs):
    pass
'''


def _free_port() -> int:
    """绑 0 拿一个空闲端口。

    与子进程真正 bind 之间存在极小的 TOCTOU 窗口；真撞上了会表现为就绪超时，
    断言里会把子进程日志整段带出来，可以直接定位。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def _dump(log_path: Path, limit: int = 4000) -> str:
    """把子进程 stdout/stderr 从磁盘读出来。失败时如实报告，不掩盖主断言。"""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # pragma: no cover
        return "<读取子进程日志失败: %r>" % (e,)
    if not text:
        return "<子进程无任何输出>"
    if len(text) > limit:
        text = "...(前部截断)...\n" + text[-limit:]
    return text


def _fail(msg: str, proc, log_path: Path, base: str) -> str:
    return (
        "%s\n入口: %s\n子进程 returncode: %r\n"
        "---- 子进程 stdout/stderr ----\n%s"
    ) % (msg, base, proc.poll(), _dump(log_path))


def _start(tmp_path: Path, port: int, udp_port: int):
    """用真实入口 `python main.py` 起子进程，输出合并写到 tmp_path/child.log。"""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(parents=True, exist_ok=True)
    (stub_dir / "webbrowser.py").write_text(_BROWSER_STUB, encoding="utf-8")

    env = os.environ.copy()
    env["HUB_PORT"] = str(port)
    env["HUB_UDP_PORT"] = str(udp_port)
    env["HUB_SMOKE_BROWSER_LOG"] = str(tmp_path / "browser_url.txt")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(stub_dir) + (os.pathsep + existing if existing else "")

    log_path = tmp_path / "child.log"
    with open(log_path, "wb") as handle:
        proc = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=str(SERVER_DIR),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    return proc, log_path


def _stop(proc):
    """收尾：先 terminate，10s 内不退就 kill。绝不留下常驻进程。"""
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _wait_live(base: str, proc, timeout: float = STARTUP_TIMEOUT):
    """轮询 /health/live。就绪返回 200；子进程提前退出返回 None。"""
    deadline = time.time() + timeout
    with httpx.Client(trust_env=False, timeout=2.0) as client:
        while time.time() < deadline:
            if proc.poll() is not None:
                return None
            try:
                resp = client.get(base + "/health/live")
            except httpx.HTTPError:
                time.sleep(0.25)
                continue
            if resp.status_code == 200:
                return 200
            time.sleep(0.25)
    return None


def test_main_py_starts_and_serves(tmp_path):
    """`cd server && python main.py` 必须能真正启动并对外服务。"""
    port = _free_port()
    udp_port = _free_port()
    proc, log_path = _start(tmp_path, port, udp_port)
    try:
        base = "http://127.0.0.1:%d" % port
        code = _wait_live(base, proc)
        assert code == 200, _fail(
            "服务未能在 %.0fs 内就绪（/health/live 没返回 200）" % STARTUP_TIMEOUT,
            proc, log_path, base,
        )

        with httpx.Client(trust_env=False, timeout=5.0) as client:
            resp = client.get(base + "/")
        assert resp.status_code == 200, _fail("GET / 状态码不是 200", proc, log_path, base)

        data = resp.json()
        assert data.get("app") == "workbench-sync-server", _fail(
            "GET / 的 app 字段不符: %r" % (data,), proc, log_path, base,
        )
        assert data.get("port") == port, _fail(
            "GET / 的 port 不符（HUB_PORT 没生效？）: %r" % (data,), proc, log_path, base,
        )
        # 核心断言：lan_ip 由 `__main__` 块在 uvicorn.run 之前算好。
        # 谁把它挪走或删掉，这里立刻变 None。TestClient 覆盖不到这条路径。
        # 注意 find_lan_ip() 靠 UDP connect 拿出口 IP，需要至少一条路由；
        # 真没有路由的机器上这里会是 None，报错信息会直接指出来。
        assert data.get("lan_ip"), _fail(
            "GET / 的 lan_ip 为空——`__main__` 块里的 `LAN_IP = find_lan_ip()` 没生效，"
            "或本机没有任何出网路由。\n响应: %r" % (data,),
            proc, log_path, base,
        )

        # 启动日志必须干净。漏 `import time` 那次，崩的是 UDP 广播 daemon 线程，
        # uvicorn 和所有接口都正常，上面几条断言全绿 —— 只有这里能抓住。
        output = _dump(log_path)
        assert "NameError" not in output, _fail(
            "启动日志里出现 NameError——`__main__` 块或它起的线程漏了 import",
            proc, log_path, base,
        )
        assert "Traceback (most recent call last)" not in output, _fail(
            "启动日志里出现 traceback——启动过程有异常",
            proc, log_path, base,
        )
    finally:
        _stop(proc)


def test_main_py_exits_zero_when_port_busy(tmp_path):
    """端口被占用时走 sys.exit(0) 分支，而不是因为漏 import 抛 NameError。

    这条专门锁 `sys` —— 它只在 `__main__` 块的这个分支里被用到，
    漏了的话 `import main` 和 TestClient 都发现不了。
    """
    # 自己先占住一个端口（绑定 0.0.0.0，确保子进程 bind 0.0.0.0 一定失败）
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("0.0.0.0", 0))
    holder.listen(1)
    busy_port = holder.getsockname()[1]

    proc, log_path = _start(tmp_path, busy_port, _free_port())
    try:
        try:
            rc = proc.wait(timeout=25)
        except subprocess.TimeoutExpired:
            pytest.fail(_fail(
                "端口占用分支没有退出（预期 sys.exit(0)）", proc, log_path,
                "http://127.0.0.1:%d" % busy_port,
            ))
        output = _dump(log_path)
        assert "NameError" not in output, _fail(
            "端口占用分支抛了 NameError（多半是 `__main__` 块里漏了 import）",
            proc, log_path, "http://127.0.0.1:%d" % busy_port,
        )
        assert rc == 0, _fail(
            "端口被占用时预期退出码 0，实际 %r" % rc, proc, log_path,
            "http://127.0.0.1:%d" % busy_port,
        )
    finally:
        _stop(proc)
        holder.close()
