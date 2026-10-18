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
