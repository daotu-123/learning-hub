# -*- coding: utf-8 -*-
"""M3-P0-3：manage.py 数据目录防呆。

核心约束：
  1. 任何调用都先打印「目标数据目录：<绝对路径>」；
  2. 目标是仓库内默认 server/data 且未加 --force-default-dir 时：
       交互 → 必须明确输入 y 才放行；
       非交互 → 退出码 2，且**什么都不写**。
"""
import sys
from pathlib import Path

import pytest

import manage
from auth_sessions import account_exists


# ---------------------------------------------------------------- 工具
@pytest.fixture
def repo_default():
    """真实的仓库内默认数据目录（tests 在 server/ 下跑，__file__ 指向 server/）。"""
    return Path(manage.__file__).resolve().parent / "data"


@pytest.fixture
def noninteractive(monkeypatch):
    """把 stdin 伪装成非交互（管道 / 重定向）。"""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)


@pytest.fixture
def interactive(monkeypatch):
    """把 stdin 伪装成交互终端，并可用 answer 参数指定输入。"""
    state = {"answer": ""}
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)

    def fake_input(prompt=""):
        return state["answer"]

    monkeypatch.setattr("builtins.input", fake_input)
    return state


# ---------------------------------------------------------------- 1. 永远打印目标目录
def test_prints_target_dir_always(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(manage, "DATA_DIR", tmp_path / "elsewhere")
    assert manage.guard_data_dir(False) is None
    out = capsys.readouterr().out
    assert "目标数据目录：" in out
    # 必须是绝对路径
    printed = out.split("目标数据目录：")[1].strip().splitlines()[0]
    assert Path(printed).is_absolute()


def test_prints_absolute_path_not_relative(capsys, monkeypatch, tmp_path):
    """传相对路径进去也要打印绝对路径（否则"我在哪"这个问题没被回答）。"""
    monkeypatch.setattr(manage, "DATA_DIR", "some/relative/dir")
    manage.guard_data_dir(False)
    out = capsys.readouterr().out
    printed = out.split("目标数据目录：")[1].strip().splitlines()[0]
    assert Path(printed).is_absolute(), printed


# ---------------------------------------------------------------- 2. 非默认目录放行
def test_non_default_dir_passes(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(manage, "DATA_DIR", tmp_path / "deploy-data")
    assert manage.guard_data_dir(False) is None
    assert "拒绝执行" not in capsys.readouterr().out


# ---------------------------------------------------------------- 3. 默认目录 + 非交互 → 退出码 2
def test_default_dir_noninteractive_refuses(capsys, monkeypatch, repo_default, noninteractive):
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)
    code = manage.guard_data_dir(False)
    assert code == manage.EXIT_REFUSED_DEFAULT_DIR == 2
    out = capsys.readouterr().out
    assert "拒绝执行" in out
    assert "--force-default-dir" in out          # 输出要告诉用户怎么放行
    assert "HUB_DATA_DIR" in out                 # 以及正确做法是什么


def test_default_dir_noninteractive_writes_nothing(monkeypatch, repo_default,
                                                   noninteractive, tmp_path):
    """拒绝时必须真的什么都没写——不能"拒绝了但还是建了账号"。"""
    # 把账号文件指到临时目录，方便断言它没被创建
    import auth_sessions
    acct = tmp_path / "account.json"
    monkeypatch.setattr(auth_sessions, "ACCOUNT_JSON", acct)
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)
    monkeypatch.setattr(manage, "cmd_set_password",
                        lambda args: (_ for _ in ()).throw(AssertionError("不该被调用")))
    code = manage.main(["set-password"])
    assert code == 2
    assert not acct.exists(), "被拒绝了却还是写了账号文件"
    assert not account_exists.__doc__ or True


def test_force_default_dir_skips_guard(capsys, monkeypatch, repo_default, noninteractive):
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)
    assert manage.guard_data_dir(True) is None
    assert "跳过" in capsys.readouterr().out


# ---------------------------------------------------------------- 4. 默认目录 + 交互
def test_default_dir_interactive_yes_passes(monkeypatch, repo_default, interactive):
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)
    interactive["answer"] = "y"
    assert manage.guard_data_dir(False) is None


def test_default_dir_interactive_yes_variants(monkeypatch, repo_default, interactive):
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)
    for ans in ("Y", "yes", "YES", " y "):
        interactive["answer"] = ans
        assert manage.guard_data_dir(False) is None, ans


def test_default_dir_interactive_no_refuses(monkeypatch, repo_default, interactive):
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)
    for ans in ("", "n", "N", "no", "whatever"):
        interactive["answer"] = ans
        assert manage.guard_data_dir(False) == 1, repr(ans)


def test_default_dir_interactive_eof_refuses(monkeypatch, repo_default):
    """input() 抛 EOFError（Ctrl-D）也当拒绝，不许当成同意。"""
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)

    def boom(prompt=""):
        raise EOFError

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", boom)
    assert manage.guard_data_dir(False) == 1


# ---------------------------------------------------------------- 5. main() 集成
def test_main_noninteractive_default_dir_returns_2(monkeypatch, repo_default, noninteractive):
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)
    called = []
    monkeypatch.setattr(manage, "cmd_set_password", lambda a: called.append(a) or 0)
    assert manage.main(["set-password"]) == 2
    assert called == [], "防呆拦下了还去跑子命令"


def test_main_custom_dir_reaches_subcommand(monkeypatch, tmp_path, noninteractive):
    monkeypatch.setattr(manage, "DATA_DIR", tmp_path / "deploy-data")
    called = []
    monkeypatch.setattr(manage, "cmd_set_password", lambda a: called.append(a) or 0)
    assert manage.main(["set-password"]) == 0
    assert len(called) == 1, "非默认目录应当正常进入子命令"


def test_main_force_flag_reaches_subcommand(monkeypatch, repo_default, noninteractive):
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)
    called = []
    monkeypatch.setattr(manage, "cmd_set_password", lambda a: called.append(a) or 0)
    assert manage.main(["set-password", "--force-default-dir"]) == 0
    assert len(called) == 1


def test_main_passes_flag_through(monkeypatch, tmp_path, noninteractive):
    """--force-default-dir 要能从 args 上读到（argparse 合并子解析器参数）。"""
    monkeypatch.setattr(manage, "DATA_DIR", tmp_path / "d")
    seen = {}
    monkeypatch.setattr(manage, "cmd_set_password",
                        lambda a: seen.update(force=a.force_default_dir, reset=a.reset,
                                              username=a.username) or 0)
    manage.main(["set-password", "--force-default-dir", "--reset", "--username", "bob"])
    assert seen == {"force": True, "reset": True, "username": "bob"}


# ---------------------------------------------------------------- 6. 常量与路径解析
def test_repo_default_dir_is_sibling_of_manage_py():
    got = manage._repo_default_data_dir()
    assert got is not None
    assert got == Path(manage.__file__).resolve().parent / "data"


def test_exit_code_is_distinct_from_business_refusal():
    """2 不能和 cmd_set_password 的"账号已存在"退出码 1 撞车。"""
    assert manage.EXIT_REFUSED_DEFAULT_DIR != 1
