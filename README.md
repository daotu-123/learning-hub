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
> 前端登录页是下一轮的事；本轮**前端一行没动**，仍全部走旧路径。

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

> 缺省值是**作者本机目录**，只为「克隆下来直接能跑」。部署到其它机器（尤其 VPS）时
> 必须用环境变量覆盖，否则数据会写到不存在的路径。例：
>
> ```bash
> HUB_PORT=8637 HUB_VAULT=/srv/notes HUB_FAVORITES=/srv/favorites python main.py
> ```

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
