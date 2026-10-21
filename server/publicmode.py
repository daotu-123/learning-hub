# -*- coding: utf-8 -*-
"""M3-P5：公网模式（`HUB_PUBLIC=1`）。

## 为什么单独一个模块

公网模式的四条规则**必须能被单独测**，而且改动要集中在少数几个地方。
混进 main.py 的后果是：这些判断散落在中间件、启动横幅、UDP 线程里，
改一处漏一处，而漏掉任意一条的后果都是"公网裸奔"。

## 四条规则

1. **监听地址缺省收成 127.0.0.1**（在 config.py 里处理，TLS 由隧道/反代终结）。
2. **关闭 UDP 局域网自动发现广播**。广播是给同一广播域里的手机 App 用的；
   公网模式下它只会告诉同网段所有设备"这里有个服务"，与目的相反。
3. **关闭「回环免鉴权」豁免** —— 最高危的一条。cloudflared / tailscale funnel
   都是从**本机 127.0.0.1** 连进来的：不关豁免，所有流量都以"本机"身份进来，
   永远不需要令牌。本机桌面端因此会失效（需重新登录一次），该代价由
   `HUB_LOCAL_BYPASS=1` 显式承担（默认关，启动横幅会打印并警告）。
   **未设 `HUB_PUBLIC` 时豁免保持开启**——那是历史行为，逐字不变。
4. **必须显式指定 `HUB_DATA_DIR`**，否则**拒绝启动**（退出码 3）。
   公网模式下数据落点含糊 = 账号落在没人记得的地方。P0-3 给 manage.py 加的
   防呆拦的是同一类事故，但那是交互式的；这里是非交互式的硬闸，
   服务与 CLI 两条路径都要拦。

## 为什么第 4 条用"拒绝启动"而不是"打个警告"

服务已经要经隧道对公网开放了。这个时刻数据目录如果还是缺省值，
意味着它会落到 exe 同级或仓库内某个目录——那种位置通常不在备份脚本的
清单里，也不在任何文档写的路径上。等到发现账号建错了地方时，
账号已经建好、会话已经签发，只能重来一遍。拒绝启动的代价是
"部署时多配一个环境变量"，收益是把事故挡在服务对外之前。
"""
import os
import sys

# 硬闸专用的退出码。与 manage.py 的 2（防呆拒绝）分开：
#   2 = manage.py CLI 的防呆拒绝
#   3 = 服务启动前的公网模式硬闸
# 调用方能据此区分"是谁拒绝的"。
EXIT_PUBLIC_GUARD = 3

# 显式设了 HUB_DATA_DIR 就算"用户明确指定过"，哪怕值是空串以外的东西。
# 空串 / 纯空白视为未设置（与 config._env 一致）。
DATA_DIR_ENV = "HUB_DATA_DIR"


def data_dir_explicitly_set(env=None) -> bool:
    """用户是否显式指定过 HUB_DATA_DIR。

    注意判的是**环境变量有没有给**，而不是 DATA_DIR 最终落在哪：
    硬闸要拦的是"用户没表态"，让服务自己挑一个缺省位置。
    """
    e = os.environ if env is None else env
    v = (e.get(DATA_DIR_ENV) or "").strip()
    return bool(v)


def startup_public_guard(env=None, public=None) -> int:
    """启动前的公网模式硬闸。返回 0 = 放行；返回非 0 = 应以该退出码退出。

    只在 HUB_PUBLIC 开启时才有内容——不设 HUB_PUBLIC 时**直接放行**，
    保证本机/局域网行为与之前逐字一致。

    打印用 stderr 而不是 stdout：stdout 在打包运行时可能被 tee 进日志，
    而"拒绝启动"这种信息必须让人在第一时间看到，且不该混进业务日志。
    """
    e = os.environ if env is None else env
    if public is None:
        public = (e.get("HUB_PUBLIC") or "").strip().lower() in ("1", "true", "yes", "on")

    if not public:
        return 0

    if data_dir_explicitly_set(e):
        return 0

    print("=" * 60, file=sys.stderr)
    print("  拒绝启动：公网模式（HUB_PUBLIC=1）必须显式指定数据目录",
          file=sys.stderr)
    print("", file=sys.stderr)
    print("  公网模式下服务会经隧道/反代对外暴露，数据落点含糊等于事故：", file=sys.stderr)
    print("    · 账号会建在一个没人记得的位置", file=sys.stderr)
    print("    · 那个位置通常不在备份脚本清单里", file=sys.stderr)
    print("    · 事后发现时账号已建好、会话已签发，只能重来", file=sys.stderr)
    print("", file=sys.stderr)
    print("  请显式设置后再启动，例如：", file=sys.stderr)
    print("    set %s=D:\\LearningHub\\data" % DATA_DIR_ENV, file=sys.stderr)
    print("", file=sys.stderr)
    print("  确实只想临时在本机试跑，请把 HUB_PUBLIC 取消：", file=sys.stderr)
    print("  本机/局域网模式不需要设 HUB_PUBLIC，行为与之前完全一致。", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("  退出码 %d（未启动任何服务）" % EXIT_PUBLIC_GUARD, file=sys.stderr)
    return EXIT_PUBLIC_GUARD


def local_bypass_enabled(env=None, public=None, bypass=None) -> bool:
    """回环请求是否免令牌（免鉴权 + 免限流）。

    语义分两种，这是本项目最容易写反的一处：

        **未设 `HUB_PUBLIC`（本机/局域网模式）→ 恒为真。**
        回环豁免是这个项目十年来的既有行为——桌面端浏览器打开就是好的，
        不用登录、不用带令牌。不设 `HUB_PUBLIC` 时**必须逐字保留**，
        否则所有本机/局域网测试与桌面体验一起崩。

        **`HUB_PUBLIC=1`（公网模式）→ 只有显式 `HUB_LOCAL_BYPASS=1` 才为真。**
        因为 cloudflared / tailscale funnel 都是从**本机 127.0.0.1** 连进来的，
        继续豁免等于给公网开后门。代价是本机桌面端要重新登录一次，
        这个代价由 `HUB_LOCAL_BYPASS=1` 显式承担，且启动横幅会醒目警告。

    两个开关都要开才算开——"显式承担代价"的含义就是不会因为一个开关
    被误设而悄悄恢复豁免。
    """
    e = os.environ if env is None else env
    if public is None:
        public = (e.get("HUB_PUBLIC") or "").strip().lower() in ("1", "true", "yes", "on")
    if not public:
        # 本机/局域网模式：历史行为，逐字保留
        return True
    if bypass is None:
        bypass = (e.get("HUB_LOCAL_BYPASS") or "").strip().lower() in ("1", "true", "yes", "on")
    return bool(bypass)


def udp_discovery_enabled(public: bool) -> bool:
    """UDP 局域网自动发现广播是否开启。公网模式一律关。"""
    return not public