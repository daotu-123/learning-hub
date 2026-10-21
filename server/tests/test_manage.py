# -*- coding: utf-8 -*-
"""M3-P0-3：manage.py 数据目录防呆。

核心约束：
  1. 任何调用都先打印「目标数据目录：<绝对路径>」；
  2. 目标是默认数据目录（源码=server/data，frozen=exe 同级 data）
     且未加 --force-default-dir 时：
       交互 → 必须明确输入 y 才放行；
       非交互 → 退出码 2，且**什么都不写**。
  3. 建号成功后必须打印「已写入：<account.json 绝对路径>」（可审计落点）。
  4. frozen 与源码两种场景的提示语各自成立（别让一个覆盖另一个）。
"""
import sys
from pathlib import Path

import pytest

import auth_sessions
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


# ---------------------------------------------------------------- 7. 打包运行时
# 这一组是本轮踩出来的：初版 _repo_default_data_dir() 在 frozen 下直接返回
# None，等于**跳过防呆**。结果不带 HUB_DATA_DIR 跑 LearningHubManage.exe 时，
# 账号被写进了开发机路径 server/data——防呆在最该生效的场景下线了。
def test_frozen_mode_default_dir_is_exe_sibling(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Deploy\LearningHub\LearningHubManage.exe", raising=False)
    got = manage._repo_default_data_dir()
    assert got is not None
    assert str(got) == str(Path(r"C:\Deploy\LearningHub\data"))


def test_frozen_mode_guard_still_fires(monkeypatch, noninteractive):
    """frozen 下目标=exe 同级 data 时，防呆必须照样拦（退出码 2）。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Deploy\LearningHub\LearningHubManage.exe", raising=False)
    monkeypatch.setattr(manage, "DATA_DIR", Path(r"C:\Deploy\LearningHub\data"))
    code = manage.guard_data_dir(False)
    assert code == manage.EXIT_REFUSED_DEFAULT_DIR


def test_frozen_mode_force_flag_still_bypasses(monkeypatch, noninteractive):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Deploy\LearningHub\LearningHubManage.exe", raising=False)
    monkeypatch.setattr(manage, "DATA_DIR", Path(r"C:\Deploy\LearningHub\data"))
    assert manage.guard_data_dir(True) is None


def test_frozen_mode_explicit_data_dir_passes(monkeypatch, noninteractive):
    """设了 HUB_DATA_DIR 指到别处 → 放行（这正是防呆想引导的行为）。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Deploy\LearningHub\LearningHubManage.exe", raising=False)
    monkeypatch.setattr(manage, "DATA_DIR", Path(r"D:\LearningHub\data"))
    assert manage.guard_data_dir(False) is None


def test_frozen_hint_mentions_exe_sibling(capsys, monkeypatch, noninteractive):
    """frozen 场景的提示语要讲"exe 同级"，不能沿用仓库那套说辞。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Deploy\LearningHub\LearningHubManage.exe", raising=False)
    monkeypatch.setattr(manage, "DATA_DIR", Path(r"C:\Deploy\LearningHub\data"))
    manage.guard_data_dir(False)
    out = capsys.readouterr().out
    assert "exe 同级" in out
    assert "HUB_DATA_DIR" in out


def test_source_hint_mentions_repo(capsys, monkeypatch, repo_default, noninteractive):
    """源码场景的提示语要讲"仓库内"，且不能被 frozen 那套覆盖。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(manage, "DATA_DIR", repo_default)
    manage.guard_data_dir(False)
    out = capsys.readouterr().out
    assert "仓库内" in out
    assert "HUB_DATA_DIR" in out
    assert "exe 同级" not in out, "源码场景不该出现 exe 同级的说法"


# ---------------------------------------------------------------- 8. 可审计落点
def test_set_password_prints_audit_path(store, monkeypatch, capsys):
    """建号成功后必须打印「已写入：<account.json 绝对路径>」。

    理由：不看启动横幅的人（只截 CLI 输出、或事后翻记录）靠这一行
    确认账号写到了哪个文件。
    """
    monkeypatch.setattr(auth_sessions, "ACCOUNT_JSON", store / "account.json")
    monkeypatch.setattr(manage, "_read_secret", lambda prompt="": "unit-test-only-not-a-real-secret")
    monkeypatch.setattr(manage, "DATA_DIR", store)

    rc = manage.main(["set-password", "--force-default-dir"])
    assert rc == 0
    out = capsys.readouterr().out

    line = [ln for ln in out.splitlines() if ln.startswith("已写入：")]
    assert len(line) == 1, out
    printed = line[0][len("已写入："):].strip()
    # 必须是绝对路径，且指向真实写入的 account.json
    p = Path(printed)
    assert p.is_absolute(), printed
    assert p.name == "account.json", printed
    assert p.resolve() == (store / "account.json").resolve(), printed
    assert p.exists(), "打印的路径必须是真的存在（否则审计行在骗人）"


def test_audit_path_follows_monkeypatched_account_file(store, monkeypatch, capsys):
    """审计行必须读 auth_sessions.ACCOUNT_JSON 的**当前值**。

    如果 manage.py 写成 `from auth_sessions import ACCOUNT_JSON`，
    导入时就绑死了旧值，这里会打印真实数据目录的路径——测试要能抓住。
    """
    real = Path(r"E:\agent\androd-app\server\data\account.json")
    fake = store / "account.json"
    monkeypatch.setattr(auth_sessions, "ACCOUNT_JSON", fake)
    monkeypatch.setattr(manage, "_read_secret", lambda prompt="": "unit-test-only-not-a-real-secret")
    monkeypatch.setattr(manage, "DATA_DIR", store)

    manage.main(["set-password", "--force-default-dir"])
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if ln.startswith("已写入：")][0]
    printed = line[len("已写入："):].strip()
    assert printed != str(real), "打印的是真实数据目录，说明 ACCOUNT_JSON 被 from-import 绑死了"
    assert Path(printed).resolve() == fake.resolve()


def test_audit_path_on_reset_too(store, monkeypatch, capsys):
    """--reset 覆盖已有账号时同样要打印落点（覆盖是最需要留痕的操作）。"""
    import json

    monkeypatch.setattr(auth_sessions, "ACCOUNT_JSON", store / "account.json")
    monkeypatch.setattr(manage, "DATA_DIR", store)
    auth_sessions.set_password("tester", "unit-test-only-not-a-real-secret")
    assert (store / "account.json").exists()

    monkeypatch.setattr(manage, "_read_secret", lambda prompt="": "unit-test-only-not-a-real-secret-2")
    # 必须显式传 --username：--reset 不带它会用默认值 owner 覆盖，
    # 那是既有行为（cmd_set_password 里 args.username or DEFAULT_USERNAME），
    # 本用例要验的是"覆盖时也打印落点"，不是用户名语义。
    rc = manage.main(["set-password", "--reset", "--username", "tester", "--force-default-dir"])
    assert rc == 0
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if ln.startswith("已写入：")]
    assert len(line) == 1, out
    acct = json.loads((store / "account.json").read_text(encoding="utf-8"))
    assert acct["username"] == "tester"
    # 覆盖确实发生了：口令已换成新的
    assert auth_sessions.verify_password("unit-test-only-not-a-real-secret-2") is True
