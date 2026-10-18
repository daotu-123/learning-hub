# -*- coding: utf-8 -*-
"""writer.py 回归测试：所有绝对路径都用 monkeypatch 指到临时目录，不碰真实数据。

覆盖：
- 艾宾浩斯间隔推进（答对 / 答错两条曲线）
- 今日任务打勾（写回、备份、幂等、越界与无日记报错）
- 自建计划 CRUD 与 N 日序列
- 复习完成（写日记标记 + 推进间隔 + 当天幂等）
"""
import datetime
import json

import pytest

from hub import vault_reader as vr
from hub import writer as w


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    diary_root = tmp_path / "vault" / "日记"
    diary_root.mkdir(parents=True)
    queue = tmp_path / "review_queue.json"

    monkeypatch.setattr(w, "DATA_DIR", data)
    monkeypatch.setattr(w, "BACKUP_ROOT", data / "backups")
    monkeypatch.setattr(w, "PLANS_JSON", data / "plans.json")
    monkeypatch.setattr(w, "REVIEW_QUEUE", queue)
    monkeypatch.setattr(vr, "DIARY_ROOT", diary_root)

    today = datetime.date.today()
    month_dir = diary_root / f"{str(today.year)[2:]}年{today.month}月"
    month_dir.mkdir(parents=True, exist_ok=True)

    def write_diary(text, day=None):
        day = day or today
        p = diary_root / f"{str(day.year)[2:]}年{day.month}月" / f"{day.isoformat()}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    return {"data": data, "queue": queue, "today": today, "write_diary": write_diary}


# ---------------------------------------------------------------- 间隔推进
def test_next_interval_correct_curve():
    assert w._next_interval(0) == 7
    assert w._next_interval(7) == 15
    assert w._next_interval(15) == 30
    assert w._next_interval(30) == 60
    assert w._next_interval(60) == 120          # 超过表尾翻倍
    assert w._next_interval(120) == 240


def test_next_interval_wrong_curve():
    assert w._next_interval(0, wrong=True) == 1
    assert w._next_interval(1, wrong=True) == 2
    assert w._next_interval(2, wrong=True) == 4
    assert w._next_interval(4, wrong=True) == 7
    assert w._next_interval(7, wrong=True) == 15
    assert w._next_interval(15, wrong=True) == 30
    assert w._next_interval(30, wrong=True) == 60


# ---------------------------------------------------------------- 日记打勾
DIARY_TEXT = """# 今日

- [ ] 背单词
- [ ] 做数学题
* [x] 写周报
"""


def test_toggle_checkbox_writes_and_backups(env):
    p = env["write_diary"](DIARY_TEXT)
    w.toggle_diary_checkbox(env["today"].isoformat(), 0, True)

    text = p.read_text(encoding="utf-8")
    assert "- [x] 背单词" in text
    assert "- [ ] 做数学题" in text                 # 只动目标行
    backs = list((env["data"] / "backups").iterdir())
    assert backs and (backs[0] / p.name).exists()   # 写前备份


def test_toggle_checkbox_idempotent(env):
    p = env["write_diary"](DIARY_TEXT)
    w.toggle_diary_checkbox(env["today"].isoformat(), 1, True)
    once = p.read_text(encoding="utf-8")
    w.toggle_diary_checkbox(env["today"].isoformat(), 1, True)
    assert p.read_text(encoding="utf-8") == once    # 状态相同则不重复写


def test_toggle_checkbox_untick(env):
    p = env["write_diary"](DIARY_TEXT)
    w.toggle_diary_checkbox(env["today"].isoformat(), 2, False)
    assert "* [ ] 写周报" in p.read_text(encoding="utf-8")


def test_toggle_checkbox_out_of_range(env):
    env["write_diary"](DIARY_TEXT)
    with pytest.raises(w.HubWriteError):
        w.toggle_diary_checkbox(env["today"].isoformat(), 9, True)
    with pytest.raises(w.HubWriteError):
        w.toggle_diary_checkbox(env["today"].isoformat(), -1, True)


def test_toggle_checkbox_without_diary(env):
    with pytest.raises(w.HubWriteError):
        w.toggle_diary_checkbox("1999-01-01", 0, True)


# ---------------------------------------------------------------- 自建计划
def test_plans_add_and_load(env):
    assert w.plans_load() == []
    p = w.plans_add("机械设计冲刺")
    assert p["name"] == "机械设计冲刺" and p["id"]
    loaded = w.plans_load()
    assert len(loaded) == 1 and loaded[0]["id"] == p["id"]


def test_plans_add_rejects_bad_input(env):
    with pytest.raises(w.HubWriteError):
        w.plans_add("   ")
    with pytest.raises(w.HubWriteError):
        w.plans_add("x" * 41)
    w.plans_add("唯一")
    with pytest.raises(w.HubWriteError):
        w.plans_add("唯一")


def test_plans_toggle_and_delete(env):
    p = w.plans_add("每日复盘")
    today = env["today"].isoformat()
    got = w.plans_toggle(p["id"], today, True)
    assert got["checkins"][today] is True

    series = w.plans_series(7)
    assert "每日复盘" in series                       # 以计划名为键
    assert len(series["每日复盘"]) == 7
    assert series["每日复盘"][-1]["done"] is True      # 今天已打卡
    assert series["每日复盘"][-1]["custom"] is True

    w.plans_toggle(p["id"], today, False)
    assert w.plans_load()[0]["checkins"].get(today) is None

    assert w.plans_delete(p["id"]) is True
    assert w.plans_load() == []
    with pytest.raises(w.HubWriteError):
        w.plans_delete("nope")


def test_plans_toggle_bad_date_or_id(env):
    p = w.plans_add("计划A")
    with pytest.raises(w.HubWriteError):
        w.plans_toggle(p["id"], "2026-13-40", True)
    with pytest.raises(w.HubWriteError):
        w.plans_toggle("missing", env["today"].isoformat(), True)


# ---------------------------------------------------------------- 复习完成
def _queue(env, item):
    env["queue"].write_text(json.dumps({"items": [item]}, ensure_ascii=False), encoding="utf-8")


def test_review_done_advances_and_marks(env):
    p = env["write_diary"]("# 今日\n\n- [ ] 复习公差\n")
    _queue(env, {"concept": "错题-公差配合", "status": "active",
                 "interval_days": 7, "reviews": 0})

    r = w.review_done("公差配合")
    assert r["marker_written"] is True
    assert r["already"] is False
    assert r["item"]["interval_days"] == 15          # 错题曲线 7 → 15
    assert r["item"]["next_review"] == (
        env["today"] + datetime.timedelta(days=15)).isoformat()

    text = p.read_text(encoding="utf-8")
    assert "复习完成：公差配合" in text

    again = w.review_done("公差配合")
    assert again["marker_written"] is False           # 标记幂等
    assert again["already"] is True
    assert again["item"]["interval_days"] == 15       # 当天不重复推进


def test_review_done_without_queue(env):
    env["write_diary"]("# 今日\n")
    r = w.review_done("任意主题")
    assert r["item"] is None and r["marker_written"] is True


def test_review_done_rejects_bad_concept(env):
    with pytest.raises(w.HubWriteError):
        w.review_done("")
    with pytest.raises(w.HubWriteError):
        w.review_done("x" * 201)
