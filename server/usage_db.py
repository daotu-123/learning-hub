# -*- coding: utf-8 -*-
"""usage.db 的建表逻辑（唯一出处，M3-P0-1）。

**为什么要有这个文件**：`usage.db` 这一个文件被 5 个域共用，而建表语句
原本散落在 6 处（usage / pomodoro / legacy_life / hub/router 两处 / favorites），
且每处都只 `CREATE TABLE IF NOT EXISTS` 自己的那张表。后果是：

    新部署 → 空数据目录 → 没有 usage 表
    GET /api/summary → favorites._usage_day_counts 直接 SELECT usage
    → sqlite3.OperationalError: no such table: usage → 500

而只要先访问一次 `/api/usage`（它的连接函数会建表）再调 `/api/summary`
就恢复 200——**同一个接口的表现取决于请求顺序**，这正是散落建表的典型症状。
`/health/ready` 也把"文件不存在"当成就绪（首启时库还没建），所以探针
同样是绿的，问题只在真实业务请求上暴露。

本模块把 6 处的 `CREATE TABLE` 收成一处常量 + 一个 `connect()`。
约定：**任何读写 usage.db 的代码都必须经过 `connect()`**，
不许再自己写 `sqlite3.connect(USAGE_DB)` + `CREATE TABLE`。
新增表时只改这里的 SCHEMA，不要去调用点加语句。

注意 `legacy_life`（health 表）按 docs/gate0-decisions.md §0.5 已登记待删，
但**表与历史数据不删**，所以它的建表语句照旧保留在这里。
"""
import sqlite3

from config import USAGE_DB

# 表结构。顺序无关，但**不要改已有语句**——`IF NOT EXISTS` 意味着改了对老库
# 也不生效（老库的旧结构会被沿用），只会造成"代码改了但线上没变"的困惑。
SCHEMA = (
    # 手机使用时间统计（routers/usage.py）
    """CREATE TABLE IF NOT EXISTS usage(
        date TEXT, package TEXT, app_name TEXT, total_ms INTEGER, day_ms INTEGER,
        PRIMARY KEY(date, package))""",
    """CREATE TABLE IF NOT EXISTS usage_hourly(
        date TEXT, hour INTEGER, seconds INTEGER,
        PRIMARY KEY(date, hour))""",
    # 番茄钟（routers/pomodoro.py 与 hub/router.py 共用同一张表）
    """CREATE TABLE IF NOT EXISTS pomodoro(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL, task TEXT DEFAULT '',
        minutes INTEGER DEFAULT 25, ts TEXT)""",
    # 睡眠 / 运动（routers/legacy_life.py，登记待删但表与数据保留）
    """CREATE TABLE IF NOT EXISTS health(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL, kind TEXT NOT NULL,
        label TEXT DEFAULT '', value_min INTEGER DEFAULT 0,
        start_ts TEXT DEFAULT '', end_ts TEXT DEFAULT '',
        ts TEXT)""",
)


def ensure_schema(con: sqlite3.Connection) -> None:
    """确保 4 张表都存在。幂等，可反复调用。

    **必须 commit**：Python sqlite3 默认隔离级别下 `CREATE TABLE` 不会自动
    提交（只读路径如 /api/summary 根本不会有后续 INSERT 来顺带提交），
    不 commit 的话 close() 会把建表回滚掉，下一个连接仍然看不到表。
    原来的散落实现都有这个隐患，只是因为总有别的写请求顺带提交才没暴露。
    """
    for stmt in SCHEMA:
        con.execute(stmt)
    con.commit()


def connect(db_path=None) -> sqlite3.Connection:
    """打开 usage.db 并保证表结构存在。

    `db_path` 只为测试注入用（指向临时目录）；生产一律走 config.USAGE_DB。
    """
    con = sqlite3.connect(db_path or USAGE_DB)
    ensure_schema(con)
    return con
