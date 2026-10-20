# -*- coding: utf-8 -*-
"""M2c-P1：限流（登录退避 + 全局令牌桶 + 上传限频）。

## 为什么自己实现而不是用 slowapi / fastapi-limiter

那两个库都要求"限流器 = 存储后端"，默认内存后端同样是**每 worker 一份**，
也就是说它们并不解决我们真正要说明的那个问题（多 worker 下计数不一致），
却引入了"框架版本耦合 + 装饰器或依赖注入改路由"的结构性代价。
本项目是**单进程单账号**部署（Gate 0 §0.1），限流逻辑必须能被讲清楚、
能被测试直接验证，而不是藏在一个库的内部策略里。

## 三个独立机制（互不干扰，判定顺序固定）

### 1. 登录退避（按 来源IP × 账号 组合计数）
只作用于 `POST /api/auth/login`。计数键 = (client_ip, username)。

- 连续失败 N 次（默认 5）后进入退避，**第 N+1 次起**在尝试前先查退避。
- 退避时长 = `1s × 2^(连续失败次数 - N)`，上限 60s。
  例：第 5 次失败 → 1s；第 6 次 → 2s；第 7 次 → 4s；… 第 11 次起 → 60s 封顶。
- 窗口 15 分钟：最后一次失败在 15 分钟前则计数清零（"连续"的定义）。
- 退避期内**直接返回 429，不进入 Argon2id 校验**——这既是防爆破的关键
  （否则攻击者可以无成本地持续消耗 CPU 做口令哈希），也让退避真的省事。
- 成功登录 → 该键计数清零。

### 2. 全局令牌桶（按来源 IP）
覆盖 `/api/*` 以外的**全部** API 请求（`/api/` 前缀，含 `/api/v1/` 别名路径）。

算法（标准令牌桶，非滑动窗口计数）：

    桶容量 C（burst），补充速率 r = limit / 60（token/秒）
    请求到达时：
        now = monotonic()
        tokens = min(C, tokens + (now - last) * r)     # 惰性补充，不开后台线程
        last = now
        if tokens >= 1: tokens -= 1; 放行
        else:           429 + Retry-After

用 `time.monotonic()` 而不是 `time.time()`：后者会被 NTP 校时回拨，
回拨后 `now - last` 为负 → 桶被"灌满"，等于限流失效。
惰性补充意味着**没有请求时桶自然填满**，也意味着没有任何后台线程与定时器。

### 3. 上传限频（按来源 IP）
`/api/hub/wallpaper`、`/api/photo/upload` 单独一个更紧的固定窗口。
理由：这两个端点是**唯一会写磁盘 + 吃内存**的入口（base64 解码后最多
20MB）。全局桶的阈值按"人类浏览"标定，对批量上传来说太松。

## 回环豁免

回环请求（127.0.0.1 / ::1 / localhost）**完全不受任何限流**。
这不是漏洞：回环意味着请求来自本机浏览器或本机进程，
而本机上的攻击者已经拥有你的文件系统权限，限流对他没有意义，
只会先把自己的桌面端和测试打死（开发时页面的并发请求就能把登录按钮锁住）。

## 计数存进程内存 —— 这是已知的、有意接受的限制

**当前实现：所有计数在进程内存的 dict 里。单进程部署下完全正确。**

一旦改成多 worker（uvicorn --workers 4、或 gunicorn + 多进程、
或前面挂多个容器副本），每个进程各有一份计数，实际阈值会变成
`配置值 × worker 数`，且登录退避在 worker A 上触发不影响 worker B——
攻击者只要把请求轮询到另一个 worker 就能绕过退避。

届时必须换成外部共享存储（Redis / Memcached 至少要原子 INCR + EXPIRE）。
本模块把存储访问收敛在三个函数里（`_hit_login`、`_hit_bucket`、`_hit_upload`），
换存储只需要改这三个函数的函数体，判定逻辑与阈值语义不用动。
这一条已写进 README「反向代理与公网部署」，别只写在这里。

## 429 响应形状（新形状，刻意与 401 不同）

    HTTP/1.1 429 Too Many Requests
    Retry-After: <秒数，整数，至少 1>
    {"error":"rate_limited","detail":"<一句话>","retry_after":<秒数>}

为什么 401 的形状一个字没动、429 另起炉灶：
401 的字面量被前后端测试逐字节锁定（M2a/M2b 都验过"逐字节一致"），
它的语义是"你的凭据不对"。429 的语义是"你太频繁了"，
两者混用会让前端无法区分"要重新登录"和"等一会儿就好"——
而这恰好是本轮前端要做的分支判断。前端读 `error` 字段即可。
"""

import threading
import time

# ---------------------------------------------------------------- 默认阈值
# 这些数字是**建议值**，全部可通过环境变量覆盖（见 config.py）。
# 标定依据写在每个常量旁边，改动时请连带更新理由。
DEFAULT_LOGIN_MAX_FAILURES = 5      # 连续失败几次后开始退避
DEFAULT_LOGIN_BASE_DELAY = 1.0      # 第一次退避 1s
DEFAULT_LOGIN_MAX_DELAY = 60.0      # 封顶 60s
DEFAULT_LOGIN_WINDOW = 15 * 60      # 15 分钟内算"连续"

# 全局桶：单账号自用，浏览一个页面约 10~20 个请求，看板轮询一分钟几次。
# 120/min 相当于允许"每秒 2 个请求的持续速率 + 120 的突发"，
# 正常人（切页、刷新、后台轮询）远远够用；扫描器会在几分钟内撞满。
DEFAULT_API_LIMIT_PER_MIN = 120
DEFAULT_API_BURST = 60              # 桶容量 = 允许的突发量

# 上传：一天随手拍几张到几十张，给 12/min 已经很宽松，
# 而 20MB × 12/min = 240MB/min 的写入速率已经足够打满磁盘。
DEFAULT_UPLOAD_LIMIT_PER_MIN = 12
DEFAULT_UPLOAD_BURST = 4

# 闲置桶的清理间隔：避免长期运行后 dict 里堆满一次性 IP。
_SWEEP_INTERVAL = 300.0


class Bucket:
    """单个令牌桶。**非线程安全**，由 RateLimiter 的锁保护。"""

    __slots__ = ("tokens", "last", "capacity", "rate")

    def __init__(self, capacity: float, rate: float):
        self.capacity = float(capacity)
        self.rate = float(rate)
        self.tokens = float(capacity)   # 起步即满：否则冷启动第一分钟连 1 个请求都不给
        self.last = time.monotonic()

    def take(self) -> float:
        """取一个令牌。成功返回 0.0，失败返回需要等待的秒数。"""
        now = time.monotonic()
        # 惰性补充。注意用 monotonic：wall clock 回拨会让 delta 为负。
        delta = now - self.last
        if delta > 0:
            self.tokens = min(self.capacity, self.tokens + delta * self.rate)
            self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        # 缺多少就得等多久 / 每秒补充多少
        return (1.0 - self.tokens) / self.rate


class LoginBackoff:
    """登录退避表：键为 (ip, username)。

    语义（M2c 实测踩出来的坑，务必别改回"按失败时刻算"）：
        退避的计时基准是**上一次尝试**，不是上一次失败。
        最初实现把到期判成 `now - last_fail > delay`，结果退避永不解禁——
        攻击者（或手抖的 owner）每 1 秒发一次请求，就永远停在"还差 0.1 秒"的
        状态里，一次都试不出去。正确语义是：**距上次尝试至少 d 秒**，
        所以每次尝试（包括被 429 挡掉的）都必须刷新 last_try。
    """

    __slots__ = ("fails", "last_try")

    def __init__(self):
        self.fails = 0
        self.last_try = 0.0

    def record_try(self, now: float, window: float) -> None:
        """记一次尝试（结果未知也要记）。计数 +1，刷新计时基准。"""
        if now - self.last_try > window:
            # 超过窗口 → 之前的失败不算数，重新从 1 开始
            self.fails = 1
        else:
            self.fails += 1
        self.last_try = now

    def delay_for(self, now: float, window: float,
                  max_failures: int, base: float, cap: float) -> float:
        """**剩余**退避秒数；0 表示现在可以尝试。"""
        if self.fails < max_failures:
            return 0.0
        if now - self.last_try > window:
            return 0.0
        # fails == max_failures → base；再往后每多尝试一次翻倍
        step = min(self.fails - max_failures, 30)   # 上限防 2**1000 溢出
        d = min(cap, base * (2 ** step))
        remaining = d - (now - self.last_try)
        return remaining if remaining > 0 else 0.0


class RateLimiter:
    """三合一限流器。线程安全（单把 RLock 足够：临界区都是 O(1) 运算）。"""

    def __init__(
        self,
        api_limit_per_min: int = DEFAULT_API_LIMIT_PER_MIN,
        api_burst: int = DEFAULT_API_BURST,
        upload_limit_per_min: int = DEFAULT_UPLOAD_LIMIT_PER_MIN,
        upload_burst: int = DEFAULT_UPLOAD_BURST,
        login_max_failures: int = DEFAULT_LOGIN_MAX_FAILURES,
        login_base_delay: float = DEFAULT_LOGIN_BASE_DELAY,
        login_max_delay: float = DEFAULT_LOGIN_MAX_DELAY,
        login_window: float = DEFAULT_LOGIN_WINDOW,
    ):
        self.api_rate = api_limit_per_min / 60.0
        self.api_capacity = float(api_burst)
        self.upload_rate = upload_limit_per_min / 60.0
        self.upload_capacity = float(upload_burst)
        self.login_max_failures = login_max_failures
        self.login_base = login_base_delay
        self.login_cap = login_max_delay
        self.login_window = login_window

        self._lock = threading.Lock()
        self._buckets = {}          # ip -> Bucket（全局 API）
        self._upload_buckets = {}   # ip -> Bucket（上传）
        self._login = {}            # (ip, username) -> LoginBackoff
        self._last_sweep = time.monotonic()

    # ---------------------------------------------------------------- 内部
    def _sweep_locked(self, now: float) -> None:
        """清掉长期不用的条目。阈值：桶已满且 5 分钟没动过。"""
        if now - self._last_sweep < _SWEEP_INTERVAL:
            return
        self._last_sweep = now
        for table in (self._buckets, self._upload_buckets):
            for k in [k for k, b in table.items() if b.tokens >= b.capacity and now - b.last > _SWEEP_INTERVAL]:
                del table[k]
        for k in [k for k, b in self._login.items() if now - b.last_try > self.login_window * 2]:
            del self._login[k]

    # ---------------------------------------------------------------- 1. 登录退避
    def login_try(self, ip: str, username: str) -> float:
        """**扣一次尝试额度**并返回剩余退避秒数。

        调用位置刻意放在鉴权之前：退避期内的请求也要消耗一次尝试，
        否则"退避到期 → 放行 → 又立刻被顶回去"会形成活锁。
        """
        now = time.monotonic()
        with self._lock:
            st = self._login.get((ip, username))
            if st is None:
                st = self._login[(ip, username)] = LoginBackoff()
            # 先按旧计数算剩余，再记账（本次尝试本身不延长本次退避）
            remaining = st.delay_for(now, self.login_window, self.login_max_failures,
                                     self.login_base, self.login_cap)
            st.record_try(now, self.login_window)
            return remaining

    def login_success(self, ip: str, username: str) -> None:
        """登录成功 → 该键清零。"""
        with self._lock:
            self._login.pop((ip, username), None)

    # ---------------------------------------------------------------- 2. 全局桶
    def api_take(self, ip: str) -> float:
        now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            b = self._buckets.get(ip)
            if b is None:
                b = self._buckets[ip] = Bucket(self.api_capacity, self.api_rate)
            return b.take()

    # ---------------------------------------------------------------- 3. 上传
    def upload_take(self, ip: str) -> float:
        now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            b = self._upload_buckets.get(ip)
            if b is None:
                b = self._upload_buckets[ip] = Bucket(self.upload_capacity, self.upload_rate)
            return b.take()

    # ---------------------------------------------------------------- 观测
    def stats(self) -> dict:
        with self._lock:
            return {
                "api_buckets": len(self._buckets),
                "upload_buckets": len(self._upload_buckets),
                "login_keys": len(self._login),
            }

    def reset(self) -> None:
        """清空全部计数。测试用。"""
        with self._lock:
            self._buckets.clear()
            self._upload_buckets.clear()
            self._login.clear()


# ---------------------------------------------------------------- 全局实例
# 阈值在模块加载时从 config 读；测试可以直接构造独立实例。
def build_default() -> RateLimiter:
    from config import (
        HUB_LOGIN_MAX_FAILURES, HUB_LOGIN_BASE_DELAY, HUB_LOGIN_MAX_DELAY,
        HUB_LOGIN_WINDOW, HUB_API_LIMIT_PER_MIN, HUB_API_BURST,
        HUB_UPLOAD_LIMIT_PER_MIN, HUB_UPLOAD_BURST,
    )
    return RateLimiter(
        api_limit_per_min=HUB_API_LIMIT_PER_MIN,
        api_burst=HUB_API_BURST,
        upload_limit_per_min=HUB_UPLOAD_LIMIT_PER_MIN,
        upload_burst=HUB_UPLOAD_BURST,
        login_max_failures=HUB_LOGIN_MAX_FAILURES,
        login_base_delay=HUB_LOGIN_BASE_DELAY,
        login_max_delay=HUB_LOGIN_MAX_DELAY,
        login_window=HUB_LOGIN_WINDOW,
    )


LIMITER = build_default()


# ---------------------------------------------------------------- 上传端点清单
# 只列"写磁盘 + 吃内存"的入口。新增同类端点时必须同步加进来。
UPLOAD_PATHS = frozenset({
    "/api/hub/wallpaper",
    "/api/photo/upload",
})


def is_upload_path(path: str) -> bool:
    """是否上传类端点。**兼容 /api/v1 别名**（改写中间件在更外层，
    所以这里看到的是改写后的 /api/* 路径；但仍做一次 v1 归一，
    避免中间件注册顺序被改动时静默漏掉限流）。"""
    p = path
    if p.startswith("/api/v1/"):
        p = "/api/" + p[len("/api/v1/"):]
    return p in UPLOAD_PATHS


def retry_after(delay: float) -> int:
    """Retry-After 取整，**至少 1**——0 会被部分客户端当成"立即重试"，
    从而把退避变成一个纯装饰。"""
    return max(1, int(delay + 0.999))
