# -*- coding: utf-8 -*-
"""M2c-P4：安全响应头。

**为什么 CSP 同时出现在两个地方**（这是本文件最容易误解的一点）：

    1) `web/index.html` 里的 `<meta http-equiv="Content-Security-Policy">`
       —— 覆盖 **APK**。APK 用 WebViewAssetLoader 以
       `http://appassets.androidplatform.net/www/index.html` 加载页面，
       这个响应**根本不经过本服务器**，只靠 meta 才拦得住。
    2) 本模块的响应头 `Content-Security-Policy`
       —— 覆盖 **Web /app**，并且**唯一能带 frame-ancestors**。
       `frame-ancestors` 在 `<meta>` 里会被浏览器直接忽略（规范如此），
       防点击劫持只能走响应头。

两处内容**必须一致**（下面 header 版 = meta 版 + frame-ancestors）：
浏览器会把 meta 与响应头**同时生效并取交集**，若 header 少写或写宽，
并不会"覆盖"meta，而是叠加——看起来"服务端配了 CSP 其实没约束住"，
正是这种不一致最隐蔽。两处只要有一处漏改，就等于放宽了策略，
所以**改 CSP 必须同时改这两个地方**，测试 tests/test_security_headers.py 会断言它们一致。

CSP 正文不在本模块拼装字符串再手抄一遍，而是由 tests 校验；
改动请同步 web/index.html。
"""

# 与 web/index.html 的 meta 完全一致（不含 frame-ancestors：那里写了也不生效）
CSP_META = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    # 只放开 style **属性**，不放 <style>/样式表。
    # 原因（实测得出，勿当成多余项删掉）：Vue 把模板里的静态 style="flex:1"
    # 编译成 `el.style.cssText = "flex:1"`，Chrome 按 inline style 走 style-src 检查，
    # 在 style-src 'self' 下会被拦，控制台报
    # "Applying inline style violates … style-src 'self'"。
    # 加 style-src-attr 后 <style> 与样式表依然必须同源，脚本依然禁内联。
    "style-src-attr 'unsafe-inline'; "
    "img-src 'self' data: blob: http: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' http: https:; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "base-uri 'self'; "
    "form-action 'none'"
)

# 响应头版 = meta 版 + frame-ancestors
CSP_HEADER = CSP_META + "; frame-ancestors 'none'"

# 只对 SPA 页面下 CSP 头。**不给 /hub**：
# server/hub_web/hub.html 里有内联 <style> 与内联 <script>（老页面，未迁移到 Vue），
# 套上去会直接把旧中枢打挂。在不重构旧页面的前提下不给它加 CSP，
# 是"先不弄坏"与"不假装有防护"之间的取舍；旧页面无 XSS 面（内容全部来自
# 自己的 JSON 且经 md 转义），且 /hub 本身已被 X-Token 之外的静态页规则约束。
CSP_HEADER_PATHS = ("/app",)

# 始终下发的头（对所有响应，含 401/429/静态资源）
ALWAYS_HEADERS = {
    # 日记/照片/壁纸 URL 里带 sig 与 exp，Referer 若外泄等于把签名地址送出去。
    # no-referrer 同时堵掉"从搜索/外站点进来时泄露完整 URL"。
    "Referrer-Policy": "no-referrer",
    # 防止浏览器把非 CSS/JS 的响应按脚本嗅探执行（MIME 混淆是自建服务的经典坑）。
    "X-Content-Type-Options": "nosniff",
    # 老浏览器不支持 CSP frame-ancestors 时的兜底。
    "X-Frame-Options": "DENY",
    # 禁掉老 IE 的 DNS 预解析（现代浏览器已忽略该头，保留无害）。
    "X-DNS-Prefetch-Control": "off",
}


def should_send_csp(path: str) -> bool:
    """判断该路径是否下发 CSP 响应头。"""
    for p in CSP_HEADER_PATHS:
        if path == p or path.startswith(p + "/"):
            return True
    return False