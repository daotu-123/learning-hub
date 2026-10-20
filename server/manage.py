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
"""
import argparse
import getpass
import sys

from auth_sessions import (
    MIN_PASSWORD_LENGTH,
    account_exists,
    load_account,
    revoke_all_sessions,
    set_password,
)

DEFAULT_USERNAME = "owner"


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
    sp.set_defaults(func=cmd_set_password)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
