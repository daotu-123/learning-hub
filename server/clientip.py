# -*- coding: utf-8 -*-
"""M2c-P2：X-Forwarded-For 的正确采信。

## 攻击模型（这才是重点）

`X-Forwarded-For` 是一个**任何客户端都能自己写的请求头**。如果无脑采信：

    POST /api/auth/login
    X-Forwarded-For: 8.8.8.8
    ... 重复 10 次，每次换一个 IP

那么限流的计数键每次都是新的 → **限流完全失效**。
所以"怎么解析 XFF"不是一个格式问题，而是一个安全问题。

## 规则

1. 直连来源（TCP 对端）**不在** `HUB_TRUSTED_PROXIES` 里 → **完全不采信 XFF**，
   客户端 IP = 直连来源。
2. 直连来源在受信列表里 → 采信 XFF，但**从右往左**找**第一个不在受信列表里**的地址，
   那个就是真实客户端 IP。
   - 为什么从右往左：XFF 的约定是 `XFF: client, proxy1, proxy2`，**越靠右越靠近服务器**，
     越靠左越可能是客户端伪造的。每一跳代理都会把自己的地址追加到右边，
     所以右边的部分由受控基础设施生成、可信；只有最左边那跳是客户端能写的。
   - 如果整条链全部受信（例如两层反代），取**最左**那个（也就是列表里的第一个）——
     它是最后一个受信实体看到的那一跳。
   - 找不到非受信地址时（全是受信），返回最左值，行为等价于上条。

`HUB_TRUSTED_PROXIES` 支持 CIDR（`10.0.0.0/8`）与单个 IP，默认**空**
——空 = 不信任任何代理 = 所有部署在反代后面时都必须显式配置，
否则限流会把整个反代当成一个 IP（一个人用满额度，全家被限）。

隧道场景的一个补充：cloudflared 回源时会**保留客户端自己写的 XFF**，
真实客户端 IP 放在 `CF-Connecting-IP`。这不影响本模块的核心规则
（从右往左取第一个非受信地址照样能择出真实客户端），所以
`request_client_ip` 只在 XFF 缺失时才把 CF 头当补充。

## 端口与非法值

XFF 里的项可能是 `1.2.3.4:5678`（带端口），也可能是 `unknown`。
带端口的用 `rsplit(':', 1)` 剥掉；非法值直接跳过。
只有 IPv4/IPv6 字面量进入判断，不做 DNS 解析——**绝不能把主机名交给
socket.gethostbyname**，那既是 SSRF 也是一次可被用作放大攻击的 DNS 查询。
"""

import ipaddress
import os
from typing import List, Optional

from config import HUB_TRUSTED_PROXIES


def is_loopback(host: str) -> bool:
    """判断是否来自本机。

    与 main._loopback **同一份判定**（M2c 把它搬到这里共用）：
    登录端点也需要它来做限流豁免，而 common.py 明确禁止放鉴权相关代码，
    从 main import 又会成环（main → routers.auth → main）。
    main._loopback 现在只是转调本函数，行为逐字不变。
    """
    if not host:
        return False
    return host in ("127.0.0.1", "::1", "localhost")


def _parse_addr(raw: str) -> Optional[ipaddress._BaseAddress]:
    """解析一个地址字面量；非法返回 None（不抛异常，不做 DNS）。"""
    v = (raw or "").strip()
    if not v:
        return None
    # 去掉端口：`1.2.3.4:5678` → `1.2.3.4`
    if v.count(":") == 1 and "." in v:
        v = v.rsplit(":", 1)[0]
    try:
        return ipaddress.ip_address(v)
    except ValueError:
        return None


class TrustedProxies:
    """受信代理集合。支持 IP 与 CIDR。"""

    def __init__(self, entries: List[str]):
        self.nets = []
        for e in entries or []:
            s = (e or "").strip()
            if not s:
                continue
            try:
                self.nets.append(ipaddress.ip_network(s, strict=False))
            except ValueError:
                # 配置写错不该让服务起不来，但必须留证据——否则会退化成
                # "限流按代理 IP 计数"却没人知道
                print("  [警告] HUB_TRUSTED_PROXIES 里有非法条目，已忽略：%r" % s)

    def __contains__(self, addr) -> bool:
        if addr is None:
            return False
        # 版本不匹配时 ip_network.__contains__ 返回 False 而不是抛异常
        for n in self.nets:
            try:
                if addr in n:
                    return True
            except TypeError:
                continue
        return False

    def __bool__(self):
        return bool(self.nets)


# 从 config 读一次（测试可 monkeypatch 本模块的 TRUSTED）
TRUSTED = TrustedProxies(HUB_TRUSTED_PROXIES)


def client_ip(peer_host: str, xff_header: Optional[str]) -> str:
    """算出用于限流计数的客户端 IP。

    peer_host  = TCP 直连来源（request.client.host）
    xff_header = X-Forwarded-For 整串，可为 None / 空

    返回值永远是"可直接作为 dict 键"的字符串。
    """
    peer = _parse_addr(peer_host)
    if peer is None:
        # 拿不到合法 IP（理论上不会，Unix socket 时可能为空）：
        # 退化成用原始字符串，仍然能限流（只是同组会被合并）
        return peer_host or "unknown"
    # 不可信来源 → XFF 一律不看
    if peer not in TRUSTED:
        return str(peer)
    if not xff_header:
        return str(peer)

    items = [x.strip() for x in xff_header.split(",")]
    items = [x for x in items if x]
    if not items:
        return str(peer)

    # 从右往左找第一个非受信地址
    for raw in reversed(items):
        addr = _parse_addr(raw)
        if addr is None:
            continue
        if addr not in TRUSTED:
            return str(addr)
    # 全链受信 → 取最左（最后一个受信实体看到的那一跳）
    leftmost = _parse_addr(items[0])
    return str(leftmost) if leftmost is not None else str(peer)


def request_client_ip(request) -> str:
    """从 Starlette Request 取。供中间件与端点共用。

    头优先级：`X-Forwarded-For` → `CF-Connecting-IP` → TCP 直连来源。

    **为什么 CF-Connecting-IP 排在 XFF 后面而不是前面**：
    Cloudflare Tunnel（cloudflared）在回源时**保留客户端发来的
    X-Forwarded-For**，而它自己写的真实客户端 IP 放在 `CF-Connecting-IP`。
    也就是说经隧道进来的流量，XFF 里最左边那一项是**客户端可写的**
    （攻击者会把自己伪造的值塞在最左边）。

    这里没有直接采信 CF 头，而是靠 client_ip() 的"从右往左取第一个非受信
    地址"规则把它择出来：受信代理（cloudflared 本身，通常是 127.0.0.1）
    追加在右边的部分由受控基础设施生成，从右往左跳过受信项后遇到的第一项
    就是真实客户端。所以 CF-Connecting-IP 在这里只作为
    "XFF 缺失/全受信时的补充"，不单独成为信任来源。
    """
    peer = request.client.host if request.client else ""
    xff = request.headers.get("x-forwarded-for")
    ip = client_ip(peer, xff)
    # XFF 完全没给（或整条链都受信、退化成 peer）时，看 CF 头。
    # 注意这里**只在 peer 受信时**才看 CF 头——不受信来源伪造
    # CF-Connecting-IP 和伪造 XFF 一样无效。
    cf = request.headers.get("cf-connecting-ip")
    if cf and peer_is_trusted(peer) and (not xff or xff.strip() == ""):
        parsed = _parse_addr(cf)
        if parsed is not None and parsed not in TRUSTED:
            return str(parsed)
    return ip


def peer_is_trusted(peer_host: str) -> bool:
    """直连来源是否在受信代理列表里（解析失败一律视为不可信）。"""
    peer = _parse_addr(peer_host)
    return peer is not None and peer in TRUSTED
