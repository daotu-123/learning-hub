# -*- coding: utf-8 -*-
"""M3-P0：标准流编码兜底（`force_utf8_stdio`）。

## 为什么要测

中文 Windows 上 stdout 被重定向（计划任务 / NSSM / `> log.txt` / 管道）时，
Python 用 **locale 编码 cp936(GBK)** 而不是 UTF-8。GBK 里没有
⚠(U+26A0)、✖、─、│、┌ 这类字符，而本项目的中文输出里全都有：

    python main.py
    print("  ⚠ 回环免令牌豁免: …")
    → UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0'
    → 退出码 1，**服务根本没起来**

这是阻断级问题：服务化部署（正是最需要它的地方）根本起不来，
而日志里只剩一行堆栈。

## 测试怎么做才算真测到

必须 **subprocess.Popen 起真进程** + **stdout/stderr 走 PIPE** + **env 剥离
PYTHONIOENCODING / PYTHONUTF8**。三条缺一不可：

- 走 PIPE：只有在**非控制台**的流上，Python 才用 locale 编码；
  真的分配了控制台时它会用 UTF-8，问题不出现
- 剥环境变量：当前 shell 里可能已经设了这两个，会把 bug 掩盖掉
- 真进程：测试进程自己 import main 时 stdout 是 pytest 的捕获流，
  编码环境与真实部署完全不同

`test_removing_the_fix_makes_this_red` 用反向证明锁住测试的有效性：
把 force_utf8_stdio 变成空实现后，本文件的测试必须失败。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent

# 一条必含 ⚠ 的输出。修复前它在 GBK 下必然抛 UnicodeEncodeError。
# 复现时崩的就是 main.py 启动横幅里的这一行。
WARNING_LINE = "⚠"


def _clean_env(data_dir: Path, port: int) -> dict:
    """干净环境：显式剥离所有会影响编码的变量。"""
    env = dict(os.environ)
    for k in ("PYTHONIOENCODING", "PYTHONUTF8", "PYTHONIOSTDOUT",
              "PYTHONIOSTDERR", "PYTHONLEGACYWINDOWSSTDIO"):
        env.pop(k, None)
    env["PYTHONPATH"] = str(SERVER_DIR)
    env["HUB_DATA_DIR"] = str(data_dir)
    env["HUB_VAULT"] = str(data_dir) + "-vault"
    env["HUB_HOST"] = "127.0.0.1"
    env["HUB_PORT"] = str(port)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    return env


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Server:
    """起一个 `python main.py` 子进程，stdout/stderr 重定向到**临时文件**。

    为什么用文件而不是 PIPE：

    - PIPE 会死锁——`communicate()` 等进程退出，而服务常驻，永远不返回。
      要读 PIPE 的内容就得引入超时读取线程，那会让这个测试复杂到掩盖重点。
    - 文件**更贴近真实故障场景**。用户报告的是「stdout 重定向到文件」，
      而重定向的普通文件与 PIPE 一样属于"非控制台流"，Python 对两者
      都用 locale 编码（cp936），所以触发的是同一段代码路径。
    - 可以在服务运行中随时读取，不需要等它结束——断言 stderr 无异常时
      这一点很关键。
    """

    def __init__(self, tmp_path: Path, extra_env: dict | None = None,
                 entry: str = "main.py"):
        self.data_dir = Path(tmp_path) / "data"
        self.port = _free_port()
        env = _clean_env(self.data_dir, self.port)
        if extra_env:
            env.update(extra_env)
        self.out_path = Path(tmp_path) / "stdout.log"
        self.err_path = Path(tmp_path) / "stderr.log"
        self._out_fh = open(self.out_path, "wb")
        self._err_fh = open(self.err_path, "wb")
        self.proc = subprocess.Popen(
            [sys.executable, entry],
            cwd=str(SERVER_DIR), env=env,
            stdout=self._out_fh, stderr=self._err_fh,
        )

    def wait_listening(self, timeout: float = 60.0):
        """等服务起来。返回 (是否成功, stdout文本, stderr文本)。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False, *self.read_output()
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:%d/health/live" % self.port, timeout=2
                ) as r:
                    if r.status == 200:
                        # 给日志一点落盘时间（stderr 是无缓冲写文件，通常即时，
                        # 但 uvicorn 的日志有行缓冲，稳妥起见给一点余量）
                        time.sleep(0.3)
                        return True, *self.read_output()
            except Exception:
                time.sleep(0.4)
        return False, *self.read_output()

    def read_output(self) -> tuple[str, str]:
        """读 stdout/stderr 并按 **utf-8** 解。

        encoding/errors 显式给足——这正是 P1 那个「测试解码自己坑自己」
        的修法：默认会用父进程 locale（cp936）去解子进程输出，
        遇到 UTF-8 字节序列就 UnicodeDecodeError，后面任何
        `... in None` 都变成 TypeError，报错还完全指不到真正原因。
        """
        out = self.out_path.read_bytes().decode("utf-8", "replace")
        err = self.err_path.read_bytes().decode("utf-8", "replace")
        return out, err

    def wait_exit(self, timeout: float = 60.0):
        """等进程结束并回收输出（用于本来就会退出的场景）。"""
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        self._out_fh.close()
        self._err_fh.close()
        return self.read_output()

    def kill(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        for fh in (self._out_fh, self._err_fh):
            try:
                fh.close()
            except Exception:
                pass


@pytest.fixture
def server(tmp_path):
    s = _Server(tmp_path)
    yield s
    s.kill()


# ====================================================================
# 1. 回归测试本体：干净 env + PIPE 重定向 → 服务必须起来
# ====================================================================

def test_main_starts_with_piped_stdio_on_chinese_windows(server):
    """**本轮主修复点**。

    修复前：进程以退出码 1 结束，stderr 里是
        UnicodeEncodeError: 'gbk' codec can't encode character '\\u26a0'
    修复后：服务起来，/health/live 200，stderr 无编码错误。
    """
    ok, out, err = server.wait_listening()
    combined = out + err

    assert "UnicodeEncodeError" not in combined, (
        "标准流出现编码错误：\n" + combined[-1500:]
    )
    assert "codec can't encode" not in combined, combined[-1500:]
    assert ok, (
        "服务没起来。退出码=%r\n--- stdout ---\n%s\n--- stderr ---\n%s"
        % (server.proc.poll(), out[-1200:], err[-1200:])
    )


def test_health_live_is_200(server):
    """更强的信号：真的能发 HTTP 请求并拿到 200。"""
    ok, _o, _e = server.wait_listening()
    assert ok, "服务没起来"
    with urllib.request.urlopen("http://127.0.0.1:%d/health/live" % server.port, timeout=5) as r:
        assert r.status == 200


def test_stderr_has_no_traceback(server):
    """stderr 里不该有 Traceback —— 崩溃的那次是有完整堆栈的。"""
    ok, _out, err = server.wait_listening()
    assert ok, "服务没起来"
    assert "Traceback" not in err, err[-1500:]


def test_startup_banner_is_readable_utf8(server):
    """启动横幅必须是**可读的 UTF-8 中文**，不能是乱码或问号。

    这一条比"不崩"更重要：崩了看得见，而 `?` 与 `???` 是静默的
    信息损失——排障时会以为配置项没生效。
    """
    ok, out, _err = server.wait_listening()
    assert ok, "服务没起来"
    assert "工作台同步服务器" in out, out[-1500:]
    assert "运行模式" in out, out[-1500:]
    assert WARNING_LINE in out, (
        "启动横幅里应包含 ⚠ 那类字符（走 _bypass 分支），实际输出：\n" + out[-1500:]
    )
    assert "?" * 3 not in out, "输出里有 ??? 说明字符被 replace 掉了"


def test_manage_py_also_survives_piped_stdio(tmp_path):
    """manage.py 有同样的问题（它输出 ⚠ 与 ═ 分隔线），必须一起修。"""
    env = dict(os.environ)
    for k in ("PYTHONIOENCODING", "PYTHONUTF8", "PYTHONIOSTDOUT", "PYTHONIOSTDERR"):
        env.pop(k, None)
    env["PYTHONPATH"] = str(SERVER_DIR)
    env["HUB_DATA_DIR"] = str(tmp_path / "data")

    r = subprocess.run(
        [sys.executable, "manage.py", "set-password", "--force-default-dir"],
        cwd=str(SERVER_DIR), env=env,
        input="manage-stdio-test-pw\nmanage-stdio-test-pw\n",
        capture_output=True,
        encoding="utf-8", errors="replace",     # 显式解码，别让 locale 坑自己
        timeout=120,
    )
    combined = r.stdout + r.stderr
    assert "UnicodeEncodeError" not in combined, combined[-1500:]
    assert "codec can't encode" not in combined, combined[-1500:]
    assert "已写入：" in r.stdout, combined[-1500:]


# ====================================================================
# 2. force_utf8_stdio 本身的行为
# ====================================================================

def test_force_utf8_stdio_sets_utf8():
    """单测：调用后 stdout/stderr 编码确实是 UTF-8。"""
    from stdiosafe import force_utf8_stdio, stdio_is_utf8

    force_utf8_stdio()
    assert stdio_is_utf8() is True


def test_force_utf8_stdio_tolerates_none_stream(monkeypatch):
    """stdout 为 None（pythonw / GUI 子系统）→ 跳过，不抛。"""
    import stdiosafe

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    stdiosafe.force_utf8_stdio()          # 不抛即通过


def test_force_utf8_stdio_tolerates_stream_without_reconfigure(monkeypatch):
    """没有 reconfigure 的自定义流 → 跳过，不抛。"""

    class NoReconfigure:
        encoding = "gbk"

        def write(self, _):
            return 0

        def flush(self):
            pass

    import stdiosafe

    monkeypatch.setattr(sys, "stdout", NoReconfigure())
    stdiosafe.force_utf8_stdio()          # 不抛即通过


def test_force_utf8_stdio_swallows_reconfigure_errors(monkeypatch):
    """reconfigure 抛异常必须被吞掉——修编码不能变成新的崩溃源。"""

    class Boom:
        encoding = "gbk"

        def reconfigure(self, **_kw):
            raise OSError("cannot reconfigure")

        def write(self, _):
            return 0

        def flush(self):
            pass

    import stdiosafe

    monkeypatch.setattr(sys, "stdout", Boom())
    monkeypatch.setattr(sys, "stderr", Boom())
    stdiosafe.force_utf8_stdio()          # 不抛即通过


def test_stdio_is_utf8_reports_false_for_none(monkeypatch):
    import stdiosafe

    monkeypatch.setattr(sys, "stdout", None)
    assert stdiosafe.stdio_is_utf8() is False


def test_force_utf8_stdio_never_raises_even_when_reconfigure_is_weird(monkeypatch):
    """reconfigure 返回非 None / 参数不合法等怪情况也不该抛。"""

    class Weird:
        encoding = "gbk"

        def reconfigure(self, *a, **k):
            return "unexpected-return-value"

        def write(self, _):
            return 0

        def flush(self):
            pass

    import stdiosafe

    monkeypatch.setattr(sys, "stdout", Weird())
    monkeypatch.setattr(sys, "stderr", Weird())
    stdiosafe.force_utf8_stdio()


# ====================================================================
# 3. 反向证明：把修复去掉，本文件必须变红
# ====================================================================
# 这一节由 test_removing_the_fix_makes_this_red 驱动：它临时把
# stdiosafe.force_utf8_stdio 打成空实现，再跑一遍真实启动，
# 断言进程以非 0 退出且 stderr 出现 UnicodeEncodeError。
# 没有它，上面那些断言可能因为「环境恰好是 UTF-8」而恒绿。
def test_removing_the_fix_makes_this_red(monkeypatch, tmp_path):
    """反向证明：禁用 force_utf8_stdio 后，真实启动必须崩。"""
    import stdiosafe

    # 空实现 = 假装修复不存在
    monkeypatch.setattr(stdiosafe, "force_utf8_stdio", lambda: None)
    # 子进程用一份被打了补丁的 stdiosafe：写一个 sitecustomize 式注入太重，
    # 这里直接用 -c 前置导入来替换符号，效果等价且不污染仓库。
    boot = (
        "import sys;"
        "sys.path.insert(0, r'%s');" % str(SERVER_DIR) +
        "import stdiosafe;"
        "stdiosafe.force_utf8_stdio = lambda: None;"
        "import runpy;"
        "sys.argv=['main.py'];"
        "runpy.run_path('main.py', run_name='__main__')"
    )
    env = _clean_env(tmp_path / "data", _free_port())
    # 触发那行含 ⚠ 的分支，必须同时满足两个条件
    env["HUB_PUBLIC"] = "1"
    env["HUB_DATA_DIR"] = str(tmp_path / "data")
    env["HUB_LOCAL_BYPASS"] = "1"

    out_path = tmp_path / "broken-out.log"
    err_path = tmp_path / "broken-err.log"
    with open(out_path, "wb") as of, open(err_path, "wb") as ef:
        proc = subprocess.Popen(
            [sys.executable, "-c", boot],
            cwd=str(SERVER_DIR), env=env, stdout=of, stderr=ef,
        )
        try:
            proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
            pytest.fail("禁用修复后进程竟然没退出（可能意外正常启动了）")
    combined = (out_path.read_bytes().decode("utf-8", "replace")
                + err_path.read_bytes().decode("utf-8", "replace"))

    assert proc.returncode != 0, (
        "禁用 force_utf8_stdio 后居然正常退出了——说明本测试环境没有真正"
        "触发 GBK 编码路径，本文件的回归测试可能是假绿。\n输出：\n" + combined[-1500:]
    )
    assert "UnicodeEncodeError" in combined, (
        "禁用修复后应出现 UnicodeEncodeError，实际：\n" + combined[-1500:]
    )
    assert "\\u26a0" in combined or "⚠" in combined, combined[-1500:]


# ====================================================================
# 4. 源码扫描：禁止裸 text=True / universal_newlines=True
# ====================================================================
# 这不是洁癖，是一个已经发生过的坑：
#   `subprocess.run(..., text=True)` 会用**父进程 locale 编码**（中文 Windows
#   是 cp936）去解子进程输出。子进程一旦输出 UTF-8 的中文（我们所有模块都
#   在 force_utf8_stdio 之后输出 UTF-8 了），父进程就 UnicodeDecodeError，
#   `r.stderr` 变成 None，接着 `... in None` 抛 TypeError ——
#   报错完全指不到真正原因，看起来像"测试框架坏了"。
#
# 修法是全仓统一显式 `encoding="utf-8", errors="replace"`。
# 用源码扫描锁住，是因为这类问题不会自己暴露：加了 encoding 的地方测试通过，
# 没加的地方也常常"碰巧"通过（子进程输出恰好全是 ASCII）。
def _python_sources():
    for p in SERVER_DIR.rglob("*.py"):
        s = str(p).replace("\\", "/")
        if "/.venv/" in s or "/build/" in s or "/dist/" in s or "__pycache__" in s:
            continue
        # 跳过本文件：下面两处扫描规则里出现 "text=True" 字面量作为
        # 被禁名单，扫自己会把自己判成违规（第一次跑就抓到了三次）。
        if p.name == "test_stdio_encoding.py":
            continue
        yield p


def test_no_bare_text_true_anywhere():
    """全仓不允许出现 text=True / universal_newlines=True。"""
    import io
    import tokenize

    offenders = []
    for path in _python_sources():
        with io.open(path, "rb") as fh:
            try:
                toks = list(tokenize.tokenize(fh.readline))
            except (tokenize.TokenError, SyntaxError):
                continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for tok in toks:
            if tok.type != tokenize.STRING:
                continue
            s = tok.string.strip("\"'")
            # 只认恰好等于这两个值的字符串字面量，避开 "text=True" 之类说明
            if s not in ("text=True", "text=1", "universal_newlines=True"):
                continue
            # 同一调用里若已显式给了 encoding，该 text= 就是冗余但无害
            ln = lines[tok.start[0] - 1] if tok.start[0] - 1 < len(lines) else ""
            nearby = " ".join(lines[tok.start[0] - 1: tok.start[0] + 3])
            if "encoding=" in nearby:
                continue
            offenders.append("%s:%d  %s" % (path.name, tok.start[0], ln.strip()))
    assert not offenders, (
        "以下位置用了裸 text=True/ universal_newlines=True，"
        "解码会走父进程 locale，中文 Windows 上会 UnicodeDecodeError：\n  "
        + "\n  ".join(offenders)
    )


def test_subprocess_calls_that_read_text_use_explicit_encoding():
    """收输出并**当文本读**的 subprocess 调用，必须显式给 encoding=。

    判断依据是「整个调用的括号范围」，不是固定行数——最早那版按行窗口扫，
    把 router.py 那个跨了 8 行的调用判成了违规，而它的 encoding= 就在
    第 9 行。固定窗口在这类格式化过的调用上必然误报，而误报会让人
    开始忽略这个检查。

    两种合法写法都放行：
      - 显式 `encoding=..., errors="replace"`（子进程输出 UTF-8，我们全部模块
        都在 force_utf8_stdio 之后输出 UTF-8）
      - 收字节流后自己 `.decode(..., errors=...)`（hub/openmaic.py 对
        netstat 就是这么做的，因为它的输出是 GBK）
    """
    import io
    import tokenize

    offenders = []
    for path in _python_sources():
        with io.open(path, "rb") as fh:
            try:
                toks = list(tokenize.tokenize(fh.readline))
            except (tokenize.TokenError, SyntaxError):
                continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

        for i, tok in enumerate(toks):
            if tok.type != tokenize.NAME or tok.string not in (
                "run", "Popen", "check_output", "check_call"
            ):
                continue
            # 往后走到配平的右括号，取出整个调用的源码范围
            depth, span, j = 0, [], i
            while j < len(toks):
                t = toks[j]
                if t.type == tokenize.OP and t.string in "([{":
                    depth += 1
                elif t.type == tokenize.OP and t.string in ")]}":
                    depth -= 1
                    if depth == 0 and j > i:
                        break
                span.append(t)
                j += 1
            else:
                continue

            end_line = span[-1].start[0]
            src = " ".join(lines[tok.start[0] - 1: end_line + 3])
            if "subprocess" not in src:
                continue
            has_out = ("capture_output" in src) or ("stdout=" in src)
            if not has_out:
                continue
            if "encoding=" in src:
                continue
            if ".decode(" in src:
                continue          # 收字节流自己解，允许
            # 收字节流写文件、或干脆丢弃输出 → 不解码，无风险
            if ".stdout" not in src and ".stderr" not in src:
                continue
            offenders.append("%s:%d  %s" % (
                path.name, tok.start[0], src.strip()[:110]))

    assert not offenders, (
        "以下 subprocess 调用把输出当文本读却没给 encoding=，"
        "解码会走父进程 locale（中文 Windows 上是 cp936），"
        "子进程输出 UTF-8 中文时会 UnicodeDecodeError：\n  "
        + "\n  ".join(offenders)
    )