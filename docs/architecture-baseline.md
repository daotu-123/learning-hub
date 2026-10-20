# 架构基线审计（architecture-baseline）

> 生成时间：2026-10-19　审计方式：**只读**，未改动任何代码。
> 覆盖对象：`server/`（FastAPI）、`android/`（WebView 单 App）、`web/`（Vue3 SPA 源码）。
> 本文件是重构前的"现状快照"，后续每轮重构完成后对照更新。
>
> **决策另见**：[`docs/gate0-decisions.md`](gate0-decisions.md)
> （2026-10-20 owner 定案：代码组织/部署/身份三维度、产品边界、题库服务化、授权边界）。
>
> **已脱敏**：本文件进公开仓库前做了路径脱敏，`<REPO>` / `<VAULT>` / `<CLASS_VAULT>` /
> `<HERMES_SCRIPTS>` / `<DEEPTUTOR_DATA>` 是占位符；实际值由各自环境变量与本机配置提供
> （M1 起统一走 `HUB_VAULT` 等配置项，不再硬编码）。

---

## 0. 结论速览

| 维度 | 现状 |
|---|---|
| 进程形态 | 单 FastAPI 进程（`server/main.py`），PyInstaller 打成无窗口 exe，端口 **8637** |
| 路由前缀 | **扁平路径**，没有 `/api/v1`；三套前缀：`/api/*`（工作台）、`/api/hub/*`（学习中枢）、`/api/hub/openmaic/*`（AI 课堂） |
| 网页端 | 两套并存：`/hub` 旧版单页（`hub_web/hub.html`）+ `/app` 新版 Vue SPA（`web_dist/app`） |
| 客户端 | 单个 APK `com.xinghui.learninghub`，三 Tab 合一，WebView 以 **http 虚拟源**加载 |
| 鉴权 | X-Token 头 / `?token=`，**非回环 + `/api/` 路径**才校验 |
| 数据 | 全部落本机：`server/data/` + Obsidian vault（E 盘）+ F/E 盘 hermes 账本 |

---

## 1. 架构图与职责

```
                        ┌──────────────────────────────────────────────┐
   手机 APK (WebView)   │  PC: 学习中枢服务.exe  (FastAPI + uvicorn)      │
   http://appassets…    │                                              │
        │               │  main.py            进程入口 / 中间件 / 工作台路由 │
        │  http://      │    ├─ /api/*        收藏、日记、健康、照片、AI   │
        │  192.168.x.x  │    ├─ /hub, /server.js, /hub/*   旧版单页      │
        │  :8637        │    └─ /app, /app/*               新版 SPA      │
        └───────────────┤                                              │
                        │  hub/router.py     /api/hub/*   学习中枢        │
                        │    ├─ 只读：overview/today/plans/review/…      │
                        │    ├─ 写：task/review-done/plan*（走 writer）   │
                        │    └─ 热更新：webversion/webfile + sha256      │
                        │                                              │
                        │  hub/openmaic.py   /api/hub/openmaic/*         │
                        │    └─ 拉起/停本地 OpenMAIC、文档索引、生成课堂  │
                        │                                              │
                        │  hub/vault_reader.py  只读解析 Obsidian        │
                        │  hub/queue_reader.py  只读 hermes 账本 JSON     │
                        │  hub/writer.py        唯一写入口（备份+原子替换）│
                        └──────────────────────────────────────────────┘
                                     │                    │
                        <REPO>\server\data          <VAULT>
                        （settings/plans/…）        （日记、DeepTutor、收藏）
```

| 文件 | 行数 | 职责 |
|---|---|---|
| `server/main.py` | 1447 | FastAPI 实例、CORS + 鉴权 + PNA 三个中间件、工作台 `/api/*`、`/hub` 旧页、`/app` 新版 SPA 静态托管、UDP 广播自动发现、`uvicorn.run` 入口 |
| `server/hub/router.py` | 509 | 学习中枢全部读写端点、设置/壁纸、番茄钟、**网页热更新清单（sha256）**、AI Key 存取、netinfo |
| `server/hub/openmaic.py` | 623 | OpenMAIC 子进程生命周期、本机文档扫描索引、课堂生成任务队列 |
| `server/hub/vault_reader.py` | 242 | 只读解析 vault：日记 checkbox/积分/进度、DeepTutor 反馈、收藏库统计 |
| `server/hub/queue_reader.py` | 84 | 只读 `hermes-scripts` 账本：复习队列、积分、公式轮换、休息日 |
| `server/hub/writer.py` | 264 | **唯一写入口**：日记 checkbox 回写、复习完成、自建计划 CRUD；先备份再 `os.replace` |

---

## 2. 全部 HTTP 端点清单

> 前缀三条：`/api/*`、`/api/hub/*`、`/api/hub/openmaic/*`。**不存在 `/api/v1`。**

### 2.1 `server/main.py`（`@app.*`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/auth/token` | 取访问令牌，**仅回环**（否则 403） |
| GET | `/hub` | 旧版学习中枢入口页（`hub_web/hub.html`） |
| GET | `/server.js` | 旧页公共模块 |
| GET | `/hub/{path:path}` | 旧页静态资源 |
| GET | `/app` | 新版单 App SPA 入口 |
| GET | `/app/{path:path}` | SPA 静态资源（空 path → `index.html`） |
| GET | `/api/tasks` | Obsidian Tasks 任务列表 |
| POST | `/api/tasks/add` | 新增任务 |
| POST | `/api/tasks/patch` | toggle / delete / timeEntry |
| POST | `/api/health` | 心跳上报 |
| GET | `/api/health` | 心跳查询 |
| POST | `/api/daily-report` | 日报写入 vault `工作台日报/{date}.md` |
| GET | `/api/daily-report` | 读日报 |
| GET | `/api/doc` / PUT | 读 / 写 vault 内文档 |
| GET | `/` | 工作台首页 |
| GET | `/api/summary` | 汇总 |
| GET | `/api/deeptutor/notes` | DeepTutor 当日笔记 |
| GET | `/api/favorites` | 抖音/小红书当日收藏（120s 缓存） |
| GET | `/api/deeptutor` | DeepTutor 活动 |
| GET/POST | `/api/usage` | 手机使用时间 |
| POST/GET | `/api/pomodoro` | 番茄钟记录 |
| GET/PUT | `/api/diary` | 日记读 / 写（带 mtime 冲突保护） |
| GET/PUT | `/api/settings` | 工作台设置 |
| GET | `/img/{path:path}` | vault 通用图片服务（`![[路径]]`） |
| POST | `/api/photo/upload` | 照片上传 |
| GET | `/api/photos` | 照片列表 |
| GET | `/photos/{month}/{name}` | 照片文件 |
| POST | `/api/ai/chat` | DeepSeek 对话（Key 在 PC 端配置） |
| GET | `/api/ai/context` | 取 AI 上下文 |

### 2.2 `server/hub/router.py`（`@router.*`，前缀 `/api/hub`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/PUT | `/api/hub/settings` | 中枢设置（壁纸/强调色/玻璃度/场景） |
| POST | `/api/hub/wallpaper` | base64 上传壁纸（≤15MB） |
| GET | `/api/hub/wallpapers/{name}` | 壁纸文件 |
| GET/POST | `/api/hub/focus` | 番茄钟趋势 / 记录 |
| GET | `/api/hub/overview` | 打卡热力图 + 积分趋势 |
| GET | `/api/hub/today` | 今日视图（日记+复习+反馈） |
| GET | `/api/hub/plans` | 计划进度（日记计划 + 自建计划） |
| POST | `/api/hub/task` | 日记任务打勾（写 vault） |
| POST | `/api/hub/review-done` | 复习完成（写 vault + 推进间隔） |
| POST | `/api/hub/plan` `/plan-toggle` `/plan-delete` | 自建计划 CRUD |
| GET | `/api/hub/review` `/feedback` `/library` `/state` | 复习队列 / 反馈 / 收藏统计 / 系统状态 |
| GET | `/api/hub/webversion` | **热更新版本 + 文件清单（含 sha256）** |
| GET | `/api/hub/webfile/{name:path}` | **热更新取文件文本内容** |
| GET/PUT | `/api/hub/aiconfig` | DeepSeek Key 状态（脱敏）/ 保存 |
| GET | `/api/hub/netinfo` | 局域网 IP + Tailscale 地址（**免鉴权**） |

### 2.3 `server/hub/openmaic.py`（`@router.*`，前缀 `/api/hub/openmaic`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/hub/openmaic/status` | 服务状态 + 当前配置 |
| POST | `/api/hub/openmaic/start` `/stop` | 拉起 / 停止子进程 |
| GET/PUT | `/api/hub/openmaic/config` | roots/node/pnpm/端口等 |
| GET | `/api/hub/openmaic/docs` | 本机文档索引 |
| GET | `/api/hub/openmaic/doc` | 单篇全文（限 roots 内） |
| POST | `/api/hub/openmaic/generate` | 生成课堂（merge / each / topic） |
| GET | `/api/hub/openmaic/jobs` | 任务列表 |
| POST | `/api/hub/openmaic/jobs/clear` | 清已完成/失败任务 |

---

## 3. 数据落盘位置

### 3.1 `server/data/`（`<REPO>\server\data\`，gitignore）

| 路径 | 内容 | 写入方 |
|---|---|---|
| `settings.json` | 全局设置：`hub`（壁纸/强调色/玻璃度/slogan/scene）、`ai.deepseek_key`、`openmaic`（roots/node/端口）、`auth_token`（惰性生成） | `main.py`、`router.py`、`openmaic.py` |
| `plans.json` | 手机端自建计划 + 打卡 | `writer.plans_*` |
| `favorites_index.json` | 收藏扫描缓存（TTL 120s） | `main.scan_favorites` |
| `openmaic_jobs.json` | 课堂生成任务队列 | `openmaic.py` |
| `usage.db` | SQLite：`pomodoro` 表（番茄钟）、使用时间 | `main.py` / `router.py` |
| `wallpapers/` | 自定义壁纸 `custom-<日期>-<uuid>.<ext>` | `router.hub_wallpaper_upload` |
| `backups/<时间戳>/` | 每次写 vault 前的副本，保留最近 30 份 | `writer.py` |
| `openmaic_logs/` | OpenMAIC 子进程 stdout/stderr | `openmaic.py` |
| `server.log` | **uvicorn 访问日志 + 应用日志**，2MB×3 轮转 | `LOG_CONFIG` |

### 3.2 Obsidian vault

- 主 vault：`<VAULT>`
  - `日记/`（每日日记、checkbox 任务、复习标记）、`DeepTutor/`（每日反馈/文章/周记/月记）、`TaskNotes/Tasks/`、`工作台日报/`、`工作台照片/`、`deeptutor/`
- 收藏库 vault：`<CLASS_VAULT>`（抖音收藏、小红书收藏）
- 前端还有 3 处 `obsidian://open?vault=self-improve…` 深链（`hubStore.ts`、`FeedbackView.vue`、`TodayView.vue`）

### 3.3 外部账本

- `<HERMES_SCRIPTS>\*.json`：`review_queue.json`（艾宾浩斯）、`score_state.json`、`formula_rotation.json`、`skip_dates.json` —— 只读
- `<DEEPTUTOR_DATA>\`：`chat_history.db`、`logs\deeptutor.jsonl` —— 只读

### 3.4 `server/web_dist/`

| 路径 | 用途 |
|---|---|
| `web_dist/app/` | **新版 SPA 构建产物**：`index.html` + `qbank-data.js` + `assets/*.{js,css}`。同时供两处消费：① FastAPI `/app/*` 静态托管；② 同步进 APK `assets/www`；③ 热更新清单的源目录 |
| `web_dist/VERSION` | 整数版本号，**放在 `app/` 之外**（vite `emptyOutDir` 会清空 outDir） |

> 当前状态：8 个文件，全部被 git 跟踪（见 8-d）。

---

## 4. Android 侧

### 4.1 页面加载（`MainActivity.java`）

- 虚拟源 Origin：**`http://appassets.androidplatform.net`**（`MainActivity.java:45-46`）
  - `setHttpAllowed(true)`（:65）——用 http 而非 https：页面要直连 LAN 的 `http://192.168.x.x:8637`，https 页调 http 会被当混合内容拦掉
- 入口：`http://appassets.androidplatform.net/www/index.html`（`ENTRY`）
- 两个 `PathHandler`：
  - `/www/` → `WwwHandler`（:259-280）：**`files/www`（热更新缓存）优先 → 缺失回落 `assets/www`**；`.html` 强制 `no-cache`
  - `/bg/` → `BgHandler`（:283-301）：`filesDir/bg_*.jpg` 背景图，因此不需要开放 `file://`
- 资源响应统一带 `Access-Control-Allow-Origin: *` + 显式 MIME（:243-249）
- `setAllowFileAccess(false)`（:73）；`setDomStorageEnabled(true)`
- 外链规则（:87-105）：非本虚拟源 + 非 LAN 的 http/https 交给系统浏览器；LAN 留在 WebView 内
- `webView.addJavascriptInterface(bridge, "Native")`（:78）——网页侧全局对象名 **`window.Native`**
- `onBackPressed` 先问网页 `window.__goBackApp`，无上级才退出（:200-210）
- 启动时 `bridge.startDiscovery()` + `bridge.migrateWebCache(2)` + `reloadPortal()`（:150-153）

### 4.2 `JsBridge` 暴露的原生方法（`JsBridge.java`，403 行）

**带 `@JavascriptInterface`（网页 `window.Native.*` 可调）：16 个**

| # | 方法 | 用途 |
|---|---|---|
| 1 | `savePref(key, value)` | 写 SharedPreferences |
| 2 | `loadPref(key, def)` | 读 SharedPreferences |
| 3 | `getDeviceInfo()` | 设备信息 |
| 4 | `startDiscovery()` | UDP 广播发现服务器 |
| 5 | `discoverServers()` | 返回已发现服务器列表 |
| 6 | `getWebVersion()` | 本地网页版本号 |
| 7 | `saveWebFile(name, content)` | **写 `files/www/<name>`**（热更新落盘） |
| 8 | `setWebVersion(version)` | 记录网页版本 |
| 9 | `reloadApp()` | 重载入口页 |
| 10 | `clearWebCache()` | 清空 `files/www` |
| 11 | `setReminder(json)` | 设置提醒 |
| 12 | `getReminder()` | 读提醒 |
| 13 | `downloadImage(url)` | 下载图片（相册/本地） |
| 14 | `pickBackground()` | 调起相册选背景图 |
| 15 | `getBackgroundUri()` | 当前背景图 URI |
| 16 | `clearBackground()` | 清除背景图 |

**不带注解的 public 方法（仅 Java 侧内部调用，网页不可见）：4 个** —— `migrateWebCache(schema)`（:171）、`scheduleReminder(...)`（:234）、`rescheduleAfterBoot()`（:260）、`saveBackgroundUri(uri)`（:378）。

---

## 5. 热更新链路

```
① 触发      web/src/App.vue onMounted → checkWebUpdate()
             条件：IS_APP && window.Native.saveWebFile && getServer() 非空
② 版本比对  GET {server}/api/hub/webversion   带 X-Token
             hotupdate.ts:62-67
             服务端：router.py:367-397 → VERSION 文件 + rglob 目录出 [{name,sha256}]
             本地：Native.getWebVersion()（prefs "web_version"，默认 1）
             man.version <= cur → 直接返回（不更新）
③ 拉文件    for 每个文件：hotupdate.ts:70-78
             过滤：TEXT_EXT 白名单（html/js/mjs/css/json/svg/map）；无 sha256 的跳过
             GET {server}/api/hub/webfile/{encodePath(name)}
             服务端：router.py:400-412（路径穿越校验 + 返回 UTF-8 文本）
④ 校验      hotupdate.ts:82-83
             客户端 crypto.subtle 算 SHA-256(UTF-8) hex，与清单 sha256 大小写不敏感比对
             ≠ 或算不出 → 跳过该文件（"宁可停在旧版，也不执行未校验的代码"）
⑤ 写盘      Native.saveWebFile(name, content)   JsBridge.java:148
             → files/www/<name>
⑥ 记录      Native.setWebVersion(man.version)    JsBridge.java:166
⑦ 重载      Native.reloadApp() → MainActivity.reloadPortal() → loadUrl(ENTRY)
             下次 /www/ 请求由 WwwHandler 优先命中 files/www
```

失败语义：单文件失败不影响其它文件（:85）；`ok === 0` 则不 setWebVersion、不重载（:87）；整体异常静默，保持内置页面（:91-92）。

---

## 6. 鉴权与 CORS 完整行为

### 6.1 鉴权中间件（`main.py:637-663`，`@app.middleware("http")`）

判定顺序，**任一条命中即放行**：

1. 路径不是 `/api/` 开头 → 放行（静态页面/资源，否则页面打不开）——`main.py:648-649`
2. 路径在 `AUTH_EXEMPT_API` → 放行。集合 = **`{"/api/hub/netinfo", "/api/auth/token"}`**——`main.py:530`
3. 来源是回环（`127.0.0.1` / `::1` / `localhost`）→ 放行——`main.py:652-654`
4. 其余：比对令牌。取值 `X-Token` 头优先，其次 `?token=` 查询参数（`_request_token`，:554-559）；用 `secrets.compare_digest` 恒定时间比较（:657）
5. 不通过 → **401** `{"error":"unauthorized","hint":…}`

令牌来源（`auth_token()`，:540-551）：环境变量 `WORKBENCH_AUTH_TOKEN` → `settings.json.auth_token` → 都没有则 `secrets.token_urlsafe(24)` 生成并**写回 settings.json**。

补充：`GET /api/auth/token` 自身也校验回环，非回环返回 **403**（:632-633）。

### 6.2 CORS（`main.py:593-612`）

| 项 | 值 |
|---|---|
| `allow_origins` | 精确两条：`http://appassets.androidplatform.net`、`https://appassets.androidplatform.net` |
| `allow_origin_regex` | `^https?://(localhost|127.0.0.1|[::1]|192.168.\d+.\d+|10.\d+.\d+|172.(16-31).\d+.\d+|100.(64-127).\d+.\d+)(:\d+)?$` —— 本机 + RFC1918 私网 + Tailscale `100.64.0.0/10` |
| `allow_methods` / `allow_headers` | `*` / `*` |
| `allow_private_network` | **True** —— APK 源属私有网络，Chrome 发 PNA 预检；不开会被 Starlette 判 400 |
| 额外兜底中间件 | `main.py:614-620`：响应带 `Access-Control-Request-Private-Network: true` 时补 `Access-Control-Allow-Private-Network: true`（兼容老版本 Starlette） |

注意：CORS 只是"收敛面"，真正的访问控制是鉴权中间件（代码注释 `main.py:600`）。即**任意 Origin 的 `curl` 直接打 API 不受 CORS 影响，只受令牌约束**。

---

## 7. 测试脚本覆盖

### 7.1 后端 pytest（`server/tests/`，基线 36 passed）

| 文件 | 项数 | 覆盖 |
|---|---|---|
| `test_writer.py` | 14 | 间隔曲线；日记 checkbox 写回/备份/幂等/越界/无日记；计划 CRUD 与 series；复习推进与当天幂等 |
| `test_auth.py` | 10 | LAN 无令牌 401、错令牌 401、头令牌 200、`?token=` 200、netinfo 豁免、静态页不拦、回环放行、`/api/auth/token` 仅回环 |
| `test_cors.py` | 3 | PNA 预检 200 且带头、普通预检 200、实际请求带 `access-control-allow-origin` |
| `test_hotupdate.py` | 3 | 清单每项含合法 sha256；sha256 与 `/webfile` 内容实际哈希一致；`/webversion` 无令牌 401 |
| `conftest.py` | — | 导入 `main` 前固定 `WORKBENCH_AUTH_TOKEN=test-token-for-pytest-only`，避免测试依赖随机 token |

运行方式：`cd server && pytest tests -q`（`pytest.ini` 已设 `pythonpath=.`）

### 7.2 前端 Node 脚本（`web/`）

| 命令 | 脚本 | 覆盖 |
|---|---|---|
| `npm run test:qbank` | `test-qbank-store.mjs` | 题库静态 store：数据加载→组卷/搜索→判分→进度/错题→备注→打卡→卡片→导入→备份（esbuild bundle，无需后端） |
| `npm run test:qbank:ui` | `test-qbank-ui.mjs` | 题库 UI E2E：puppeteer-core + 本机 Chrome，390×844 手机视口，32 项（含"无 JS 运行错误"）。默认打 `http://127.0.0.1:8639/app/`，可用 `QB_BASE` 覆盖 |
| `npm run test:stores` | `test-hub-store.mjs` + `test-desk-store.mjs` + `test-qbank-store.mjs` | 三个 store 冒烟；hub/desk 需要**真实后端 8637 在线** |

> 已知缺口：`test-qbank-ui.mjs` 依赖 `build-tools/verify_server.py`（未入 git），默认端口 8639 与主服务 8637 不同；hub/desk store 测试要求服务已启动。

---

## 8. 八条重点核对

### a. 鉴权中间件在不在、对哪些路径生效、有哪些豁免

**确认存在。** 证据：`server/main.py:637-663`（`auth_guard`）。

- 生效范围：**仅 `/api/` 开头路径**；`/hub`、`/app`、`/`、`/img/*`、`/photos/*` 等静态路径完全不校验
- 豁免两条：`main.py:530` `AUTH_EXEMPT_API = {"/api/hub/netinfo", "/api/auth/token"}`
- 第三类放行：回环来源（`main.py:533-537` 定义 `127.0.0.1/::1/localhost`，`652-654` 生效）
- 令牌取值：`X-Token` 头 > `?token=`（`main.py:554-559`）；比较用 `secrets.compare_digest`（`657`）
- 测试锁定：`tests/test_auth.py`（10 项）

### b. CORS 白名单具体允许哪些 Origin

**确认。** 证据：`server/main.py:601-612`。

- 精确 Origin 2 条：`http://appassets.androidplatform.net`、`https://appassets.androidplatform.net`
- 正则放行：`localhost`、`127.0.0.1`、`[::1]`、`192.168.0.0/16`、`10.0.0.0/8`、`172.16.0.0/12`、`100.64.0.0/10`（Tailscale），均允许带端口
- `allow_private_network=True`（PNA 预检放行）
- 测试锁定：`tests/test_cors.py`（3 项）

### c. 热更新是否已有 sha256 校验、在哪一行

**确认，且是双向的。** 证据：

| 环节 | 位置 |
|---|---|
| 服务端生成清单 sha256 | `server/hub/router.py:387`（`hashlib.sha256(p.read_bytes()).hexdigest()`），注释 377-379 说明 2026-10-18 补此机制的背景 |
| 清单项结构 | `router.py:390`（`{name, sha256}`） |
| 客户端计算 | `web/src/native/hotupdate.ts:35-44`（`crypto.subtle.digest('SHA-256', …)`） |
| 客户端比对 | `hotupdate.ts:82-83`（不等则 `continue`） |
| 缺失 sha256 拒绝更新 | `hotupdate.ts:74` |
| 无法计算哈希也拒绝 | `hotupdate.ts:33-34, 82`（返回 null → 跳过） |
| 服务端自测一致性 | `tests/test_hotupdate.py:41-55` |

### d. `server/web_dist` 是否被 git 跟踪、多少个文件

**确认跟踪。** `git ls-files server/web_dist | wc -l` = **8**，与工作区文件数一致（`find server/web_dist -type f | wc -l` = 8）：

```
web_dist/VERSION
web_dist/app/index.html
web_dist/app/qbank-data.js
web_dist/app/assets/QbankPage-B_zpNZSN.js
web_dist/app/assets/QbankPage-iMYEqqkq.css
web_dist/app/assets/index-BPfa-_rP.js
web_dist/app/assets/index-CNp4AojP.css
web_dist/app/assets/vue-qbPTJ1M_.js
```

注意：`web/node_modules/`、`web/dist/` 在 `.gitignore`，但 `server/web_dist/`（构建产物副本）**在库内**，每次 `npm run build` 都会产生大量哈希文件名变更。

### e. Obsidian vault 路径在代码里硬编码了几处、分别在哪

**确认：共 5 处字面路径 + 3 处前端深链。**

字面路径：

| # | 位置 | 值 |
|---|---|---|
| 1 | `server/main.py:37` | `OBSIDIAN_VAULT = <VAULT>` |
| 2 | `server/hub/vault_reader.py:16` | 同上（**重复定义，未共享常量**） |
| 3 | `server/hub/openmaic.py:42` | `DEFAULT_CFG["roots"][0]` 同上 |
| 4 | `server/main.py:39` | `XHS_DIR = <CLASS_VAULT>\小红书收藏` |
| 5 | `server/hub/vault_reader.py:19` | `CLASS_DIR = <CLASS_VAULT>` |

派生子目录引用（非硬编码，但都从上面 5 个常量展开）：`main.py:38,40,750,1116,1120,1284…`、`vault_reader.py:17-18` 等。

前端软编码 vault 名 `self-improve`（`obsidian://` URI）：`web/src/hub/hubStore.ts`、`web/src/hub/FeedbackView.vue`、`web/src/hub/TodayView.vue`。

**结论：同一 vault 根在 3 个 Python 文件里各写了一遍，改路径要改 3 处。**

### f. JsBridge 暴露了多少个 `@JavascriptInterface` 方法

**确认：16 个。** 证据：`android/app/src/main/java/com/xinghui/learninghub/JsBridge.java`，`grep -c "@JavascriptInterface"` = 16（分布行 55/60/66/81/120/141/147/165/179/185/203/220/268/347/353/370）。方法清单见第 4.2 节。

补充：类内另有 4 个无注解 public 方法（`migrateWebCache:171`、`scheduleReminder:234`、`rescheduleAfterBoot:260`、`saveBackgroundUri:378`），仅供 Java 侧调用。绑定名 `Native`（`MainActivity.java:78`）。

⚠️ 文档滞后：`server/tests/test_hotupdate.py:5` 注释写"全部 13 个原生能力"，实际已是 16。

### g. 访问日志是否会记录 query string

**确认会记录，且当前无脱敏。** 证据：

- 入口：`server/main.py:1447` `uvicorn.run(app, host="0.0.0.0", port=8637, log_level="info", log_config=LOG_CONFIG)`
- `LOG_CONFIG`（`main.py:1384-1399`）**只定义了 root handler + formatter**，没有定义 `uvicorn` / `uvicorn.error` / `uvicorn.access` 三个 logger，也没有 `formatters.access`。因此 uvicorn 的 access logger 走 root（INFO + RotatingFileHandler），消息仍由 uvicorn 内部按 `'%s - "%s" %d' % (client_addr, request_line, status_code)` 拼装，`request_line` 含 **完整 URL（含 query string）**。
- 实测证据（`server/data/server.log`）：
  ```
  2026-10-18 21:38:55,980 INFO 127.0.0.1:52745 - "GET /api/hub/today?date=2026-10-18 HTTP/1.1" 200
  2026-10-18 21:38:55,984 INFO 127.0.0.1:52745 - "GET /api/diary?date=2026-10-18 HTTP/1.1" 200
  ```
- 含 `?` 的日志行共 **893 行**（`grep -c '?' server.log`）。
- 后果：`?token=<令牌>` 会明文写入 `server.log`（2MB×3 轮转）。当前日志里 `token=` 出现 0 次，但那是因为令牌机制 2026-10-18 才上线、尚无带 token 的历史请求，**不是被脱敏了**。

### h. 是否有任何令牌脱敏逻辑

**不确认（无令牌脱敏）。** 全仓库只有一处脱敏，且脱的是 AI Key 不是访问令牌：

- `server/hub/router.py:426-429`：`GET /api/hub/aiconfig` 返回 `masked = key[:3] + "***" + key[-4:]`（长度 <10 时只回"已配置"）
- **访问令牌 `auth_token` 没有任何脱敏/打码逻辑**：`/api/auth/token` 明文回传（仅限回环，`main.py:628-634`），`?token=` 明文进 access log（见 g）。
- 令牌本身 `secrets.token_urlsafe(24)` ≈ 144 bit，强度足够；风险只在"日志明文落盘 + 日志文件未纳入 .gitignore 之外的保护"（`server/data/` 已被 gitignore）。

---

## 9. 审计中发现的风险与债（不改代码，仅登记）

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| R1 | 高 | 访问日志明文记录 `?token=`；`LOG_CONFIG` 未定义 `uvicorn.access` logger，无法在不改配置的前提下过滤 | `main.py:1384-1399,1447` + `server.log` 893 行带 `?` |
| R2 | 中 | vault 根路径 3 处重复硬编码，改一处不同步会导致静默读旧库 | `main.py:37` / `vault_reader.py:16` / `openmaic.py:42` |
| R3 | 中 | `main.py` 1447 行单文件，中间件顺序（CORS→PNA→auth）与路由混排，可读性差 | `main.py` 全文 |
| R4 | 低 | `test_hotupdate.py:5` 注释写"13 个原生能力"，实际 16 | 同上 |
| R5 | 低 | UI 测试默认依赖未入库的 `build-tools/verify_server.py` 与 8639 端口，新人跑不起来 | `web/test-qbank-ui.mjs:4-5` |
| R6 | 低 | `web_dist` 哈希文件名频繁变动且入库，git 历史噪音大；`VERSION` 与 `app/` 分离靠注释约定 | `.gitignore` + `router.py:43` |
| R7 | 信息 | `settings.json` 当前不含 `auth_token` 键 → 令牌在首个非回环请求时才惰性生成并写盘；若 exe 重启且 settings.json 被清理，手机端需重新录入令牌 | `server/data/settings.json` + `main.py:540-551` |

---

## 10. 复核方式（可重复执行）

```bash
cd E:/agent/androd-app

# 端点清单
grep -n "^@app\.\(get\|post\|put\|delete\)" server/main.py
grep -n "^@router\.\(get\|post\|put\|delete\)" server/hub/router.py server/hub/openmaic.py

# 桥接方法数
grep -c "@JavascriptInterface" android/app/src/main/java/com/xinghui/learninghub/JsBridge.java   # → 16

# web_dist 跟踪状态
git ls-files server/web_dist | wc -l          # → 8
find server/web_dist -type f | wc -l          # → 8

# 硬编码路径
grep -rn "obsidian-files" server/ --include=*.py

# 日志是否带 query
grep -c '?' server/data/server.log
tail -5 server/data/server.log

# 测试基线
cd server && pytest tests -q                  # → 36 passed
```

---

*本文档由只读审计生成，未修改任何源代码；新增文件仅此 `docs/architecture-baseline.md`。*
