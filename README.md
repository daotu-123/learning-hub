# 学习中枢 Learning Hub

一套跑在家里的个人学习系统：一台电脑做服务端，三个安卓 App 各管一摊，手机与电脑随时随地同步。

写日记、打任务卡、按艾宾浩斯曲线复习、番茄钟专注、刷机械专业题、让 AI 生成课堂——数据都在自己电脑上，不上云。

---

## 组成

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  学习中枢 App │   │  机械题库 App │   │   工作台 App  │
│ com.xinghui  │   │ com.xinghui  │   │ com.xinghui  │
│ .learninghub │   │ .mechqbank   │   │ .workbench   │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       └──────────────────┼──────────────────┘
                          │ HTTP（局域网 / Tailscale 虚拟组网）
                 ┌────────▼─────────┐
                 │  FastAPI 服务 :8637 │
                 │  server/           │
                 └────────┬─────────┘
                          │
      ┌───────────────────┼────────────────────┐
      ▼                   ▼                    ▼
 Obsidian 日记      复习/积分账本         本地 SQLite
 （Markdown）       （JSON 账本）        （番茄钟等）
```

| 部分 | 说明 |
|---|---|
| `server/` | FastAPI 服务端：学习中枢 API、工作台 API、AI 课堂 |
| `hub-app/` | 学习中枢 App（WebView 套壳，页面在 `server/web_dist`） |
| `qbank-app/` | 机械题库 App（题库数据由外部脚本生成） |
| `app/` | 工作台 App（原生界面为主） |
| `apk/` | 构建产物（不入库，见 Releases） |

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
python -m venv .venv && .venv/Scripts/pip install fastapi uvicorn
.venv/Scripts/python main.py        # 监听 0.0.0.0:8637
```

打包成单文件 exe：

```bat
cd server
.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --noconfirm ^
  --name LearningHub --icon ..\exe\learninghub_icon.ico ^
  --add-data "hub_web;hub_web" --add-data "web_dist;web_dist" main.py
```

### 2. 手机 App

```bat
build_hub_apk.bat      :: 学习中枢
build_qbank_apk.bat    :: 机械题库
build_apk.bat          :: 工作台
```

需要 JDK 17 与 Android SDK（放到 `build-tools\`，构建脚本已写死相对路径）。

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

FastAPI · Uvicorn · PyInstaller · 原生 Android（WebView + Java）· Gradle 8.7 · SQLite · Obsidian Markdown

## 文档

- [`项目说明.md`](项目说明.md) —— 维护手册：目录地图、接口清单、数据位置、踩过的坑
