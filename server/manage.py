# -*- coding: utf-8 -*-
"""管理 CLI（M2a）：账号与口令。

用法（在 server/ 目录下）：

    python manage.py set-password              # 交互式设置口令
    python manage.py set-password --reset      # 覆盖已有账号，并撤销全部会话
    python manage.py set-password --username myname

行为约定：
  - 口令交互式输入两遍，**不回显**；两次必须一致；长度至少 12 位。
  - **只写 Argon2id 哈希，绝不写明文口令，也绝不打印口令。**
  - 已有账号时默认拒绝（避免误覆盖）；要覆盖必须显式加 --reset，
    而 --reset 会连带撤销该账号的全部会话（改口令即踢下线）。
  - 撤销会话不需要口令参数：改口令本身就意味着"让旧凭据全部失效"。

M3-P0-3 防呆（为什么需要）：`manage.py` 的数据目录默认是
`<仓库>/server/data`。在作者开发机上这没问题，但把仓库 clone 到部署机后，
**不设 HUB_DATA_DIR 就跑这个命令，账号会被悄悄写进 clone 目录里的
server/data**——而那地方既不在备份脚本的清单里，也不在部署文档写的
/etc 路径上，等发现时账号已经建在了错误的位置，还得重新建一遍
（建完旧会话也不会自动迁移）。所以：

  - 每次启动都先打印 `目标数据目录：<绝对路径>`，让落点一眼可见；
  - 若该路径就是仓库内默认目录且没加 `--force-default-dir`：
      交互式 → 要求明确输入 y 确认；
      非交互（管道 / 脚本 / 计划任务）→ **直接退出码 2**，什么都不写。
    非交互一律拒绝而不是默认放行：脚本里跑这个命令的人，看到的输出
    就是一封"你写错地方了"的信，而不是一个建在错误位置的账号。
"""
import argparse
import getpass
import sys
from pathlib import Path

# =====================================================================
#  M3-P0 编码安全：**必须在任何 print 之前**执行。
#  与 main.py 同一个问题（现象与理由见 stdiosafe.py 的模块注释）。
#
#  这里从 stdiosafe 导入，而不是 from main import —— 后者会因为
#  import main 而构建整个 FastAPI app 并 mkdir 数据目录：对管理 CLI 是
#  意外副作用（它正要拒绝在数据目录不明确时写入，却又顺手把那个目录建出来）。
#  复制一份则必然漂移：一个加了 errors="replace"、另一个没加，
#  就是最难查的那种不一致。
# =====================================================================
from stdiosafe import force_utf8_stdio

force_utf8_stdio()

import auth_sessions
from auth_sessions import (
    MIN_PASSWORD_LENGTH,
    account_exists,
    load_account,
    revoke_all_sessions,
    set_password,
)
from config import DATA_DIR

DEFAULT_USERNAME = "owner"

# 非交互且目标目录是仓库内默认目录时的退出码。
# 用 2 而不是 1：1 在本 CLI 里已被"账号已存在且未加 --reset"占用，
# 两者含义不同，混用会让调用方无法区分"被防呆拦下"和"业务拒绝"。
EXIT_REFUSED_DEFAULT_DIR = 2


def _resolve_data_dir() -> Path:
    """目标数据目录的绝对路径（解析掉 . 与 .. 等相对成分）。"""
    return Path(DATA_DIR).expanduser().resolve()


def _repo_default_data_dir():
    """"默认数据目录"——不显式设 HUB_DATA_DIR 时会落到那里。

    源码运行：`<本文件所在目录>/data`。
    打包运行：`<exe 所在目录>/data`（与 config._default_data_dir 保持一致）。

    用 `Path(__file__).parent` 而不是 config.HUB_ROOT：HUB_ROOT 是可以被
    环境变量改写的，"默认在哪"这个问题只有产物自己的位置说得准。

    **打包运行时的防呆不能省**：部署机恰恰是最需要它的地方。最初的实现
    在 frozen 下直接返回 None（等于跳过检查），结果不带 HUB_DATA_DIR 跑
    LearningHubManage.exe 时账号被写进了开发机路径 server/data——
    防呆在最该生效的场景下线了。
    """
    if getattr(sys, "frozen", False):
        try:
            return (Path(sys.executable).resolve().parent / "data").resolve()
        except OSError:
            return None
    try:
        return (Path(__file__).resolve().parent / "data").resolve()
    except OSError:
        return None


def _confirm(prompt: str) -> bool:
    """交互式确认。只有明确的 y/Y/yes 才算同意，其余一律视为拒绝。"""
    try:
        ans = input(prompt)
    except EOFError:
        return False
    return ans.strip().lower() in ("y", "yes")


def guard_data_dir(force_default_dir: bool):
    """防呆闸门。返回 None = 放行；返回整数 = 应以该退出码结束。

    顺带每次都打印目标目录——这行不是给防呆用的，是给"我到底写到哪了"
这个问题用的：账号文件路径不在任何输出里出现过，只有这里会讲。
    """
    target = _resolve_data_dir()
    print("目标数据目录：%s" % target)

    if force_default_dir:
        print("已显式指定 --force-default-dir，跳过「仓库内默认目录」确认。")
        return None

    repo_default = _repo_default_data_dir()
    if repo_default is None or target != repo_default:
        return None

    if getattr(sys, "frozen", False):
        hint = (
            "该路径是 exe 同级的默认数据目录（未设置 HUB_DATA_DIR 时的落点）。\n"
            "  在 exe 旁边建一个 data\\ 给本机调试用没问题；若这是正式部署，\n"
            "  账号/会话/usage.db 会跟着 exe 走，换机器、重打包都会丢掉。\n"
            "  正确做法：设置 HUB_DATA_DIR 指向固定的数据目录（如 D:\\LearningHub\\data）；\n"
            "  确实想写在 exe 旁边就加 --force-default-dir。"
        )
    else:
        hint = (
            "该路径是本仓库内的默认数据目录。\n"
            "  在开发机上这么用没问题；若这是部署机，账号会被写进 clone 目录，\n"
            "  而不是部署文档/备份脚本约定的位置。\n"
            "  正确做法：设置 HUB_DATA_DIR 指向部署数据目录；\n"
            "  确实想写这里就加 --force-default-dir。"
        )
    isatty = getattr(sys.stdin, "isatty", None)
    if isatty is not None and isatty():
        print("⚠ " + hint)
        if _confirm("确认把账号写到上面的目录吗？[y/N] "):
            return None
        print("已取消，未写入任何内容。")
        return 1

    # 非交互：一律拒绝。见模块 docstring 里"为什么不是默认放行"。
    print("拒绝执行：目标数据目录是仓库内默认目录，且未加 --force-default-dir。")
    print(hint)
    print("退出码 %d（未写入任何内容）。" % EXIT_REFUSED_DEFAULT_DIR)
    return EXIT_REFUSED_DEFAULT_DIR


def _read_secret(prompt: str) -> str:
    """读一行口令。

    非交互（管道 / 重定向）时**不能**用 getpass：Windows 上 getpass 走
    msvcrt.getwch()，它读的是**控制台**而不是被重定向的 stdin，管道输入时
    会一直等控制台输入 → 挂死。所以这里在 stdin 不是终端时退回普通读 stdin，
    并明确提示"会回显"。
    交互式终端下仍然用 getpass，输入不回显。
    """
    isatty = getattr(sys.stdin, "isatty", None)
    if isatty is not None and isatty():
        return getpass.getpass(prompt)
    print(prompt + "  [非交互模式：输入会回显]", file=sys.stderr)
    line = sys.stdin.readline()
    if not line:
        raise EOFError("没有读到口令")
    return line.rstrip("\r\n")


def _prompt_password(min_length: int) -> str:
    """交互式输入两遍口令，不回显；校验一致性与最小长度。"""
    while True:
        first = _read_secret("请输入新口令（至少 %d 位，不回显）: " % min_length)
        if len(first) < min_length:
            print("口令太短：至少需要 %d 位。" % min_length)
            continue
        second = _read_secret("请再输入一遍确认: ")
        if first != second:
            print("两次输入不一致，请重试。")
            continue
        return first


def cmd_set_password(args) -> int:
    """set-password 子命令。返回进程退出码。"""
    if account_exists() and not args.reset:
        old = load_account()
        print("已存在账号 %r。覆盖它需要显式加 --reset。" % (old.get("username") or ""))
        print("注意：--reset 会撤销该账号的全部会话（所有已登录设备都要重新登录）。")
        return 1

    password = _prompt_password(MIN_PASSWORD_LENGTH)
    acct = set_password(args.username or DEFAULT_USERNAME, password, revoke_sessions=True)

    print("账号已写入：%s" % acct.get("username"))
    # 可审计的落点。上面那行只有用户名，没有路径——而"账号到底写到哪个文件"
    # 才是排查时最常被问的问题。不看启动横幅的人（只截了 CLI 输出、
    # 或在别的机器上翻历史记录）就靠这一行。
    # 按模块属性读而不是 from-import：ACCOUNT_JSON 是导入时求值的，
    # 测试会 monkeypatch auth_sessions.ACCOUNT_JSON 到临时目录，
    # from-import 会把旧值绑死，导致这里打印真实数据目录的路径。
    account_path = Path(auth_sessions.ACCOUNT_JSON).expanduser().resolve()
    print("已写入：%s" % account_path)
    print("口令哈希已保存（Argon2id）；明文口令没有落盘，也没有打印。")
    if args.reset:
        print("已覆盖旧账号，全部会话已撤销。")
    else:
        print("已创建账号。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="manage.py",
        description="学习中枢服务端管理工具（账号 / 会话）",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("set-password", help="设置或覆盖账号口令（交互式，不回显）")
    sp.add_argument(
        "--username", default=DEFAULT_USERNAME,
        help="用户名（默认 %s）" % DEFAULT_USERNAME,
    )
    sp.add_argument(
        "--reset", action="store_true",
        help="覆盖已有账号，并撤销该账号的全部会话",
    )
    sp.add_argument(
        "--force-default-dir", action="store_true",
        help="确认把账号写进仓库内默认数据目录 server/data（不加则防呆闸门会拦）",
    )
    sp.set_defaults(func=cmd_set_password)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # 防呆闸门在任何子命令之前跑：哪怕以后加更多子命令，
    # "写到哪了"这件事也必须第一个说清楚。
    code = guard_data_dir(getattr(args, "force_default_dir", False))
    if code is not None:
        return code
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
