# 学习中枢 Learning Hub

一套跑在家里的个人学习系统：一台电脑做服务端，**一个安卓 App 内含三 Tab**（学习中枢 / 题库 / 工作台），手机与电脑随时随地同步。

写日记、打任务卡、按艾宾浩斯曲线复习、番茄钟专注、刷机械专业题、让 AI 生成课堂——数据都在自己电脑上，不上云。

---

## 组成

```
┌───────────────────────────────────────────────┐
│             学习中枢 App（单 APK 三 Tab）        │
│  com.xinghui.learninghub                      │
│  学习中枢 │ 题库 │ 工作台                        │
│  WebView(WebViewAssetLoader) + 原生桥 Native    │
└──────────────────┬────────────────────────────┘
                   │ HTTP（局域网 / Tailscale 虚拟组网）
          ┌────────▼─────────┐
          │  FastAPI 服务 :8637 │
          │  server/           │
          └────────┬─────────┘
                   │
   ┌───────────────┼────────────────────┐
   ▼               ▼                    ▼
Obsidian 日记   复习/积分账本         本地 SQLite
（Markdown）    （JSON 账本）        （番茄钟等）
```

同一份网页产物双端复用：Web 走 FastAPI 的 `/app/` 静态托管，APK 走 `assets/www`。

| 部分 | 说明 |
|---|---|
| `server/` | FastAPI 服务端：三端 API + AI 课堂 + 网页热更新清单 |
| `web/` | 前端工程（Vue 3 + Vite + TS），三 Tab 单页应用，产物在 `server/web_dist/app` |
| `android/` | 安卓工程（单 APK，WebViewAssetLoader 加载网页 + 原生桥） |
| `apk/` | 构建产物（不入库，见 Releases） |
| `legacy/` | 历史三 App 工程（`app/`、`qbank-app/`），仅作存档 |

## 功能

- **今日**：日记里的任务列表直接打勾，进度与得分实时同步到电脑
- **复习**：艾宾浩斯间隔复习，点一下推进下次间隔并写回日记标记
- **计划**：长期计划进度追踪，也可以自己新建计划每日打卡
- **专注**：番茄钟，支持后台计时与断点恢复
- **AI 课堂**：选文档或给主题，自动生成一节课
- **题库**：机械专业考研题，含错题本与薄弱点统计

## 快速开始

### 1. PC 服务

```bash
cd server
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python main.py        # 监听 0.0.0.0:8637

# 回归测试（writer 写入口：打勾 / 计划 / 复习推进 / 备份）
.venv/Scripts/python -m pytest
```

打包成单文件 exe（配置在 `server/LearningHub.spec`，已含 `hub_web` + `web_dist`）：

```bat
cd server
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean LearningHub.spec
copy /y dist\LearningHub.exe ..\exe\学习中枢服务.exe
```

### 2. 手机 App

```bat
build_apk.bat              :: 完整构建：npm run build → 同步 assets → 版本号 +1 → 出签名 APK
build_apk.bat -skip-web    :: 只重打 APK（复用已有 web 产物）
```

需要 JDK 17 与 Android SDK（放到 `build-tools\`，构建脚本已写死相对路径）。
产物：`apk\学习中枢.apk`（`com.xinghui.learninghub`）。

手机端首次打开后填服务器地址（或等 UDP 自动发现），之后连上服务即可热更新网页：
`server/web_dist/VERSION` 比 App 内版本高时，App 会自动拉取新页面并重载。

### 3. 连接

- 同一 WiFi：App 内自动发现，或填 `192.168.x.x:8637`
- 跨网络：两端装 Tailscale 登录同一账号，填 `http://100.x.x.x:8637`

## API 路径约定（/api/v1）

对外路径收敛到 `/api/v1/*`，**旧路径同时保留**，两者等价：

```
GET /api/v1/tasks   ≡   GET /api/tasks
GET /api/v1/hub/today ≡ GET /api/hub/today
```

- **实现方式是路径改写，不是路由级别名**：请求进来后先把 `/api/v1/<rest>`
  改写成 `/api/<rest>`，再交给既有路由处理。因此路由表**零新增**（仍是 73 条），
  新旧路径命中的是同一个端点函数、同一份响应，不存在"两套路由漂移"。
  实现见 `server/apiv1.py`。
- **旧路径的保留期限：覆盖已发布 APK 的一个版本周期。** 已发布的 APK 仍在打旧路径，
  同时它又会通过热更新拿到新 bundle——两条必须同时可用，直到下一个 APK 版本全量铺开。
- **前端尚未切换。** 本轮只做了服务端别名，`web/` 里的请求仍全部走旧路径。
  切换前端是单独一轮的事，会与热更新版本号一起发布。
- 边界：`/api/v1`（无尾斜杠）不猜意图，直接 404；`/health/*`、`/hub`、`/app`、
  `/img/*`、`/photos/*` 等非 `/api` 路径不受影响。
- 已知差异（刻意保留）：带尾斜杠的请求 `/api/v1/tasks/` 会被改写成 `/api/tasks/`，
  再由 Starlette 的 `redirect_slashes` 307 到 `/api/tasks`——重定向目标不带 `v1`。
  功能上不受影响（旧路径就是别名），因此没有去改写 `Location` 响应头。

## 身份与登录

单账号 + 口令（**Argon2id** 存哈希），另有一套**服务端会话令牌**。两套凭据**并行**：

| 凭据 | 携带方式 | 有效期 | 说明 |
|---|---|---|---|
| 旧共享令牌 | `X-Token` 头 或 `?token=` 参数 | 长期 | 继续有效，覆盖已发布 APK 的一个版本周期 |
| 会话令牌 | `Authorization: Bearer <session>`（也接受 `X-Token` 头） | 滑动 7 天 + 绝对上限 30 天 | 可撤销，服务端只存哈希 |

- **会话令牌只走请求头，绝不接受 query 参数**——URL 会被日志、Referer、剪贴板记录。
- 服务端**只存令牌哈希**（SHA-256），明文令牌只在登录响应里出现一次。
- 改口令 / `--reset` 会撤销全部会话（改口令即踢下线）。
- 没有账号时**服务照常启动**，只是 `POST /api/auth/login` 返回 503 并提示先建账号。

### 建账号（只需一次）

```bash
cd server
.venv/Scripts/python manage.py set-password        # 交互式输入两遍，不回显
.venv/Scripts/python manage.py set-password --reset # 覆盖已有账号（会撤销全部会话）
```

口令至少 12 位。文件落在 `server/data/account.json`（**只存哈希**），
会话落在 `server/data/sessions.json`（**只存令牌哈希**），两者都在 `.gitignore` 内。

### 端点

`/api/v1` 同名路径同样可用（M1c 的别名中间件自动覆盖）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → `{token, expires_at, username}` |
| POST | `/api/auth/logout` | 撤销当前会话 |
| GET | `/api/auth/me` | 当前会话是谁 `{username, created_at, expires_at}` |
| PUT | `/api/auth/password` | `{old_password, new_password}`，改完撤销全部旧会话并返回新会话 |

登录失败一律 401，**不区分**"用户不存在"与"口令错"（同一条消息、恒定时间比较）。
会话令牌失效（过期 / 撤销 / 伪造）与"没带令牌"返回**完全相同**的 401 响应体，不泄露原因。

> 旧共享令牌与 `WORKBENCH_AUTH_TOKEN` 环境变量属于过渡期设施，等新版 APK 铺开后移除。

### 前端登录（M2b 起）

- 路由 `/login`（懒加载）。未登录访问任何页面都会被守卫送到 `/login?next=<原路径>`，
  登录成功自动跳回；`next` 只接受站内相对路径（拒绝绝对 URL 与 `//host`）。
- 失败提示统一为「用户名或口令错误」，前端**不再**自行区分原因。
- 会话令牌存 `hub_session`（key 与后端约定一致）：APK 走 `Native.savePref/loadPref`，
  浏览器走 `localStorage`，登出与 401 **同时清两边**。
- 请求注入只有一个出口 `web/src/auth/session.ts::authHeaders()`：
  有会话用 `Authorization: Bearer <session>`，无会话但有旧令牌才回落 `X-Token`。
  **令牌永远不进 URL**（壁纸等受保护图片改为 fetch + Blob）。
- 任何 API 返回 401 → 清会话并跳 `/login?next=<当前路由>`；登录页自身的 401 不跳。
- 设置面板里有「修改口令」与「退出登录」。改口令后会用响应里返回的**新会话**替换本地令牌，
  并提示其他设备已下线。

```bash
cd web
npm run build                 # 前端构建（产物落在 server/web_dist/app）
npm run test:auth             # 身份链路验收：login → me(200) → logout(200) → me(401)
```

`npm run test:auth` 默认打 `http://127.0.0.1:8637`，可用 `HUB_BASE` 换地址，
凭据用 `HUB_ACCOUNT` / `HUB_PASSWORD` 指定。服务端还没建账号时该项会标「跳过」而不是失败。

> `/photos/*` 与 `/img/*` 目前仍走旧的 query 令牌，属于下一轮范围，本轮未改。

## 配置（环境变量）

`server/config.py` 顶部登记了全部可配置项，**不设任何环境变量时行为与原版逐字一致**：

| 变量 | 作用 | 缺省（作者本机） |
|---|---|---|
| `HUB_HOST` / `HUB_PORT` | 监听地址 / 端口 | `0.0.0.0` / `8637` |
| `HUB_VAULT` | Obsidian 主库（日记、DeepTutor、照片） | 作者本机路径 |
| `HUB_FAVORITES` | 收藏库路径（抖音 / 小红书） | 作者本机路径 |
| `HUB_HERMES_DIR` | hermes 账本目录（复习队列 / 积分） | 作者本机路径 |
| `HUB_DEEPTUTOR_DIR` | DeepTutor 数据目录 | 作者本机路径 |
| `HUB_DATA_DIR` | 服务数据目录（settings/plans/usage.db/日志） | `<HUB_ROOT>\server\data` |
| `HUB_UDP_PORT` | 局域网自动发现广播端口 | `8638` |
| `HUB_AUTH_TOKEN` | 访问令牌（可选，覆盖 settings.json 中的值） | 空 = 惰性生成 |

M2c 新增的安全相关变量（详见下文「反向代理与公网部署」）：
`HUB_TRUSTED_PROXIES`、`HUB_API_LIMIT_PER_MIN`、`HUB_API_BURST`、
`HUB_UPLOAD_LIMIT_PER_MIN`、`HUB_UPLOAD_BURST`、`HUB_LOGIN_MAX_FAILURES`、
`HUB_LOGIN_BASE_DELAY`、`HUB_LOGIN_MAX_DELAY`、`HUB_LOGIN_WINDOW`。

> 缺省值是**作者本机目录**，只为「克隆下来直接能跑」。部署到其它机器（尤其 VPS）时
> 必须用环境变量覆盖，否则数据会写到不存在的路径。例：
>
> ```bash
> HUB_PORT=8637 HUB_VAULT=/srv/notes HUB_FAVORITES=/srv/favorites python main.py
> ```

## 反向代理与公网部署

本节是把服务放到公网（VPS + 域名 + TLS）时**必须逐条落实**的东西。
M2c 的安全硬化（限流、登录退避、媒体鉴权、CSP）让公网暴露成为可能，
但下面这几条代理侧的配合**代码里管不了**，漏一条等于前面的防护被绕过。

### 1. TLS 必须在代理层 terminates

服务端只说 HTTP，**不做 TLS**。证书与私钥放在代理上：

- Caddy：直接写站点块，自动签发证书，**必须显式设置 `reverse_proxy` 头**（见下）
- Nginx：`certbot` 签发，`ssl_certificate` / `ssl_certificate_key` 挂载

对外只开 443，**不要把 8637 直接暴露到公网**。若必须直连，则用防火墙
（`ufw` / 安全组）把 8637 限制到 `127.0.0.1`，只允许代理访问。

### 2. Host 与 X-Forwarded-For（最容易配错的一条）

限流按来源 IP 计（`server/clientip.py`）。**代理不转发真实 IP，限流就退化成
"所有人共用一个配额"** —— 一台 NAT 后面的全部用户会互相触发限流；
反过来若采信了伪造的 XFF，则限流可被一条头绕过。

**默认不信任任何代理**（`HUB_TRUSTED_PROXIES` 为空 = 完全忽略 XFF）。
放到反代后面必须显式列出代理地址，多个用逗号分隔，支持 CIDR：

```bash
HUB_TRUSTED_PROXIES=127.0.0.1,10.0.0.0/8
```

代理侧（Caddy）：

```caddyfile
example.com {
    reverse_proxy 127.0.0.1:8637 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}   # 注意：不是 {http.request.header.X-Forwarded-For}
    }
}
```

> `{remote_host}` 是**连接来源 IP**。若写成
> `{http.request.header.X-Forwarded-For}`，等于把客户端可控的头原样透传，
> 攻击者可以随便填 IP 绕过限流。Caddy 的 `{client_ip}` 在有可信代理链时更稳。

Nginx：

```nginx
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $remote_addr;   # 用 $proxy_add_x_forwarded_for 之前先确认代理链可信
proxy_set_header X-Forwarded-Proto $scheme;
```

采信规则（`clientip.py`）：仅当直连来源在受信列表内才读 XFF，
并从右往左取**第一个非受信**地址；全受信则取最左。**绝不对主机名做 DNS 解析**
（那会把控制面交给攻击者的 DNS）。

### 3. 限流阈值（默认值请按自己的场景确认）

M2c 起的全部阈值都可用环境变量覆盖；**下面的值是作者按单人使用场景给的建议值，
不是拍脑袋的通用值**：

| 变量 | 默认 | 含义 |
|---|---|---|
| `HUB_API_LIMIT_PER_MIN` | `120` | 单 IP 每分钟 API 请求数 |
| `HUB_API_BURST` | `60` | 令牌桶容量，允许的突发量 |
| `HUB_UPLOAD_LIMIT_PER_MIN` | `12` | 单 IP 每分钟上传次数 |
| `HUB_UPLOAD_BURST` | `4` | 上传突发容量 |
| `HUB_LOGIN_MAX_FAILURES` | `5` | 连续失败多少次后开始退避 |
| `HUB_LOGIN_BASE_DELAY` | `1` | 退避基数（秒），实际按 `base × 2^n` 递增 |
| `HUB_LOGIN_MAX_DELAY` | `60` | 退避上限（秒） |
| `HUB_LOGIN_WINDOW` | `900` | 失败计数窗口（秒），超窗清零 |

另有 `HUB_TRUSTED_PROXIES`（见上）。调整阈值的判断依据：
桌面端是长轮询型客户端，`120/min` 相当于每秒 2 次，正常使用远达不到；
上传 `12/min` 是为了压住扫描器批量写文件。**若自架服务器还挂了别的客户端
（同一条 NAT 下的多台设备），必须调大 `HUB_API_LIMIT_PER_MIN`，否则会被自己人限死。**

回环（`127.0.0.1` / `::1`）**始终豁免**：本机桌面端不该被自己的限流打死。

> ⚠️ **多 worker 必须换外部存储**：限流计数与登录退避都放在**进程内存**里
> （`server/ratelimit.py`）。当前部署是单进程（`python main.py` / uvicorn 单 worker），
> 所以够用。一旦改成 `--workers N`，每个进程各有一份计数 → 实际阈值放大 N 倍，
> 登录退避也会被 N 个进程分摊而形同虚设。真要多 worker，得把这两个状态换成
> Redis 之类的外部存储，再谈公网。

### 4. secret 存放在哪

| 秘密 | 位置 | 说明 |
|---|---|---|
| 访问令牌 | `HUB_AUTH_TOKEN` 或 `server/data/settings.json` | 双轨凭据之一 |
| 口令哈希 | `server/data/account.json` | **只有 Argon2id 哈希**，无明文 |
| 会话 | `server/data/sessions.json` | 改口令即全部失效 |
| 媒体签名密钥 | `server/data/media_url_secret` | 惰性生成（32 字节随机），**不入仓库** |

`server/data/` 已在 `.gitignore` 内。**部署到 VPS 时**：

```bash
chmod 700 /srv/learninghub/server/data
chmod 600 /srv/learninghub/server/data/settings.json /srv/learninghub/server/data/account.json
```

媒体签名 URL 的 TTL 硬上限 300 秒（`server/media_sign.py`），签名绑定路径与
过期时间，URL 里**只有 `sig` 与 `exp`，绝不含会话令牌**；日志中 `token` / `sig`
已做打码（`server/logging_setup.py`）。

### 5. 上线前自查

- [ ] 8637 未直接对公网开放，只允许代理访问
- [ ] 域名有 TLS，HTTP 自动跳 HTTPS
- [ ] `HUB_TRUSTED_PROXIES` 已设为代理的实际地址（**不是留空**）
- [ ] 代理显式设置 `Host` 与 `X-Forwarded-For`（且用的是真实来源 IP，不是客户端可控的头）
- [ ] 限流阈值按实际使用人数确认过
- [ ] `server/data/` 权限 700，密钥文件 600
- [ ] `python manage.py set-password` 已设置账号口令（**不要只靠共享令牌**）
- [ ] 顺手验证一次：`curl -I https://你的域名/app` 应能看到
      `content-security-policy` / `x-content-type-options` / `referrer-policy` 三个头

### 6. CSP 在两处，不要只改一处

`/app` 的 CSP 出现在**两个位置**且必须一致：

1. `web/index.html` 的 `<meta http-equiv>` —— 覆盖 **APK**（APK 用
   `WebViewAssetLoader` 从 `appassets.androidplatform.net` 加载，响应不经过服务端）
2. 服务端 `Content-Security-Policy` 响应头（`server/security_headers.py`）——
   覆盖 **Web**，并且**只有它能带 `frame-ancestors`**（在 `<meta>` 里会被浏览器忽略）

浏览器对二者**取交集**，不一致 ≠ 更严，而是"看起来配了其实没约束住"。
`server/tests/test_security_headers.py` 会断言两者一致，改一处必须改另一处。

当前策略里唯一放宽的两项及理由：

- `connect-src … http: https:` —— API 地址由用户在运行时填写（LAN IP 或公网域名），
  编译期无法枚举
- `style-src-attr 'unsafe-inline'` —— Vue 把模板里的静态 `style="flex:1"` 编译成
  `el.style.cssText = "flex:1"`，Chrome 按 inline style 校验 `style-src`，不开会被拦。
  只放开 **style 属性**，`<style>` 与样式表仍必须同源（`style-src 'self'`），脚本仍禁内联。

旧 `/hub` 页**不下发 CSP**：`server/hub_web/hub.html` 还有内联 `<style>` 与内联
`<script>`，套上会直接打挂旧中枢。通用安全头（nosniff 等）照发。

## 数据与隐私

- 所有数据存在本机：Obsidian 库（日记）、JSON 账本（复习队列）、`server/data/`（设置与统计）
- 服务不做任何云端上传；AI 功能需要自备 API Key，填在本地设置里
- 写入一律先备份到 `server/data/backups/` 再原子替换，改坏了能逐份回退

## 凭证约定

签名密钥与口令**不进仓库**。首次克隆后：

```bash
cp keystore.properties.example keystore.properties
# 编辑 keystore.properties，填入自己的密钥库路径与口令
```

没有该文件时构建会自动降级（release 不签名），不影响代码阅读与调试。

## 技术栈

FastAPI · Uvicorn · PyInstaller · Vue 3 + Vite + TypeScript · 原生 Android（WebView + Java）· Gradle 8.7 · SQLite · Obsidian Markdown

## 文档

- [`项目说明.md`](项目说明.md) —— 维护手册：目录地图、接口清单、数据位置、踩过的坑
