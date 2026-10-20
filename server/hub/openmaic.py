# -*- coding: utf-8 -*-
"""
Learning Hub: OpenMAIC 集成（AI 课堂）

做什么
  - 从本机目录（Obsidian 库 / 题库 …）挑文档，调用本机 OpenMAIC 生成 AI 课堂；
  - 按需拉起 / 停止 OpenMAIC（转发服务 :8787 + Next 应用 :3000），非常驻；
  - 生成任务历史落 data/openmaic_jobs.json，刷新页面还在。

边界
  - 数据只在本机流动；生成时材料内容会发送给 OpenMAIC 所配置的模型服务商（opencode.ai）。
  - 只读本机目录里 .md/.markdown/.txt，且必须在配置的 roots 之内（防越权）。

路由：/api/hub/openmaic/*
"""
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# M1a：data 目录与 vault 根改由 config 单一来源（原为本文件硬编码）
from config import DATA_DIR as DATA_DIR_ENV, OBSIDIAN_VAULT

router = APIRouter(prefix="/api/hub/openmaic", tags=["openmaic"])

DATA_DIR = DATA_DIR_ENV
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_JSON = DATA_DIR / "settings.json"
JOBS_JSON = DATA_DIR / "openmaic_jobs.json"
LOG_DIR = DATA_DIR / "openmaic_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CFG = {
    "roots": [
        str(OBSIDIAN_VAULT),
        r"E:\obsidian\depot\homework",
        r"F:\题库",
    ],
    "openmaic_dir": r"D:\agent\openmaic",
    "setup_dir": r"E:\agent\hermes-tool\openmaic-setup",
    "node": r"D:\agent\hermes\node\node.exe",
    "pnpm": r"E:\agent\hermes-tool\pnpm\node_modules\pnpm\bin\pnpm.cjs",
    "port": 3000,
    "relay_port": 8787,
    "max_chars": 50000,
}

TEXT_EXT = {".md", ".markdown", ".txt"}
SKIP_DIRS = {
    "node_modules", ".git", ".obsidian", ".trash", ".smart-env", ".next",
    "dist", "build", "$RECYCLE.BIN", "System Volume Information",
}
MAX_FILES = 4000
MAX_DEPTH = 14
HEAD_BYTES = 8192
SCAN_TTL = 300.0

# Windows 下静默起进程（不弹控制台）
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


# ---------------------------------------------------------------- settings
def _read_settings() -> dict:
    if SETTINGS_JSON.exists():
        try:
            return json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _cfg() -> dict:
    cfg = dict(DEFAULT_CFG)
    stored = _read_settings().get("openmaic", {})
    if isinstance(stored, dict):
        cfg.update({k: v for k, v in stored.items() if v is not None})
    return cfg


def _save_cfg(patch: dict) -> dict:
    s = _read_settings()
    cur = dict(s.get("openmaic", {}))
    cur.update(patch)
    s["openmaic"] = cur
    SETTINGS_JSON.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return _cfg()


# ---------------------------------------------------------------- http helpers
def _http_json(url: str, method: str = "GET", payload: Optional[dict] = None,
               timeout: float = 8.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return json.loads(raw) if raw.strip() else {}


def _app_health(cfg: Optional[dict] = None) -> dict:
    cfg = cfg or _cfg()
    try:
        j = _http_json(f"http://127.0.0.1:{cfg['port']}/api/health", timeout=3.0)
        return {"running": bool(j.get("success")), "version": j.get("version"),
                "capabilities": j.get("capabilities")}
    except Exception as e:
        return {"running": False, "error": str(e)[:200]}


def _netstat_text() -> str:
    """netstat -ano 的文本输出。注意：中文 Windows 下是 GBK，不能按 UTF-8 解（会返回 None）。"""
    try:
        raw = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=15,
                             creationflags=CREATE_NO_WINDOW).stdout or b""
    except Exception:
        return ""
    return raw.decode("gbk", errors="replace")


def _port_listening(port: int) -> bool:
    for line in _netstat_text().splitlines():
        if f":{port} " in line and "LISTENING" in line:
            return True
    return False


def _pids_on_port(port: int) -> List[int]:
    pids = set()
    for line in _netstat_text().splitlines():
        if f":{port} " in line and "LISTENING" in line:
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(int(parts[-1]))
    return sorted(pids)


# ---------------------------------------------------------------- service control
def _spawn(cmd: List[str], cwd: str, env_extra: dict, log_name: str) -> int:
    """用 wscript + 隐藏窗口启动（返回 0；PID 不可知，停止按端口杀）。

    本机实测：Popen 起的进程即使带 DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP，
    仍会被同控制台广播的 Ctrl+C / 控制台关闭事件打死（日志尾部 `0xC000013A`
    或 `^C终止批处理操作吗`）。`WshShell.Run(cmd, 0, False)` 起的进程没有控制台，
    实测长时间存活（学习中枢自己就是这么起的）。
    """
    log_path = LOG_DIR / log_name
    with open(log_path, "ab") as fh:
        fh.write(f"\n===== {datetime.datetime.now().isoformat(timespec='seconds')} start: {' '.join(cmd)}\n".encode())

    sets = [f'set "{k}={v}"' for k, v in env_extra.items()]
    rest = " ".join(f'"{a}"' for a in cmd[1:])
    run = f'"{cmd[0]}" {rest} >> "{log_path}" 2>&1' if rest else f'"{cmd[0]}" >> "{log_path}" 2>&1'
    inner = "cmd /c " + " && ".join(sets + [run])

    vbs = LOG_DIR / ((log_name[:-4] if log_name.endswith(".log") else log_name) + ".vbs")
    vbs.write_text(
        'Set sh = CreateObject("WScript.Shell")\n'
        f'sh.CurrentDirectory = "{cwd}"\n'
        f'sh.Run "{inner.replace(chr(34), chr(34) * 2)}", 0, False\n',
        encoding="ascii",
    )
    wscript = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe")
    try:
        subprocess.run([wscript, str(vbs)], capture_output=True, timeout=30,
                       creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动失败（wscript）: {str(e)[:200]}")
    return 0


def _start_service(wait_s: int = 150) -> dict:
    """按需拉起：转发服务(:8787) + OpenMAIC 应用(:3000)。已在跑就跳过。"""
    cfg = _cfg()
    started = []
    if not _port_listening(cfg["relay_port"]):
        node = cfg["node"] if Path(cfg["node"]).exists() else "node"
        relay = str(Path(cfg["setup_dir"]) / "opencode-relay.mjs")
        if not Path(relay).exists():
            raise HTTPException(status_code=500, detail=f"转发服务脚本不存在: {relay}")
        _spawn([node, relay], cfg["setup_dir"],
               {"NODE_OPTIONS": f"--require={Path(cfg['setup_dir']) / 'dns-pin.cjs'}"},
               "relay.log")
        started.append("relay")

    if not _app_health(cfg).get("running"):
        node = cfg["node"] if Path(cfg["node"]).exists() else "node"
        script = "start" if (Path(cfg["openmaic_dir"]) / ".next" / "BUILD_ID").exists() else "dev"
        _spawn([node, cfg["pnpm"], script], cfg["openmaic_dir"],
               {
                   "NODE_OPTIONS": f"--require={Path(cfg['setup_dir']) / 'dns-pin.cjs'}",
                   "npm_config_store_dir": "D:/agent/pnpm-store",
                   "npm_config_cache_dir": "D:/agent/pnpm-cache",
               },
               f"app-{script}.log")
        started.append(f"app:{script}")

    deadline = time.time() + wait_s
    while time.time() < deadline:
        if _app_health(cfg).get("running"):
            break
        time.sleep(2.0)

    return {"started": started, **_status()}


def _stop_service() -> dict:
    cfg = _cfg()
    killed = {}
    for name, port in (("app", cfg["port"]), ("relay", cfg["relay_port"])):
        pids = _pids_on_port(port)
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=20,
                               creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass
        killed[name] = pids
    time.sleep(1.0)
    return {"killed": killed, **_status()}


def _status() -> dict:
    cfg = _cfg()
    return {
        "app": _app_health(cfg),
        "relay": {"running": _port_listening(cfg["relay_port"]), "port": cfg["relay_port"]},
        "port": cfg["port"],
        "url": f"http://localhost:{cfg['port']}",
        "roots": cfg["roots"],
    }


# ---------------------------------------------------------------- doc scan
_scan_lock = threading.Lock()
_scan_cache = {"ts": 0.0, "data": None}


def _title_of(name: str, head: str) -> str:
    m = re.search(r"^\s{0,3}#\s+(.+)$", head, re.M)
    if m:
        return re.sub(r"\s+", " ", m.group(1).strip())[:90]
    return Path(name).stem


def _excerpt_of(head: str) -> str:
    t = re.sub(r"^---\r?\n.*?\r?\n---\r?\n", "", head, flags=re.S)      # frontmatter
    t = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+.*$", "", t, flags=re.M)         # 标题行
    t = re.sub(r"```.*?```", " ", t, flags=re.S)                         # 代码块
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)                          # 图片
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)                       # 链接 → 文字
    t = re.sub(r"^\s{0,3}>\s?", "", t, flags=re.M)                       # 引用符
    t = re.sub(r"^\s{0,3}[-*+]\s+", "", t, flags=re.M)                   # 列表符
    t = re.sub(r"[*_`~]{1,3}", "", t)                                    # 强调/行内码
    t = re.sub(r"\s+", " ", t).strip()
    # 在句子边界收尾，避免半句被硬切
    if len(t) > 200:
        cut = max(t.rfind("。", 0, 200), t.rfind("；", 0, 200), t.rfind("！", 0, 200), t.rfind("？", 0, 200))
        if cut < 80:
            cut = max(t.rfind(" ", 0, 190), t.rfind("，", 0, 190))
        t = (t[:cut + 1] if cut > 0 else t[:200]) + "…"
    return t


def _approx_words(head: str, size: int) -> int:
    if size <= 0:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", head))
    en = len(re.findall(r"[A-Za-z0-9_]+", head))
    per_byte = (cjk + en) / max(len(head), 1)
    return int(per_byte * size)


def _read_head(p: Path) -> Optional[dict]:
    try:
        st = p.stat()
        if not st.st_size:
            return {"head": "", "size": 0, "mtime": st.st_mtime * 1000}
        with open(p, "rb") as fh:
            raw = fh.read(min(HEAD_BYTES, st.st_size))
        return {"head": raw.decode("utf-8", errors="ignore"),
                "size": st.st_size, "mtime": st.st_mtime * 1000}
    except Exception:
        return None


def _scan_root(root: str, budget: dict, out: list) -> dict:
    info = {"path": root, "exists": False, "count": 0}
    base = Path(root)
    if not base.is_dir():
        info["error"] = "目录不存在或盘未挂载"
        return info
    info["exists"] = True
    stack = [(base, 0)]
    while stack and budget["left"] > 0:
        d, depth = stack.pop()
        if depth > MAX_DEPTH:
            continue
        try:
            entries = list(os.scandir(d))
        except Exception:
            continue
        for e in entries:
            if budget["left"] <= 0:
                break
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name in SKIP_DIRS or e.name.startswith("."):
                        continue
                    stack.append((Path(e.path), depth + 1))
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                if Path(e.name).suffix.lower() not in TEXT_EXT:
                    continue
                meta = _read_head(Path(e.path))
                if not meta:
                    continue
                budget["left"] -= 1
                info["count"] += 1
                out.append({
                    "root": root,
                    "relPath": str(Path(e.path).relative_to(base)).replace("\\", "/"),
                    "absPath": e.path,
                    "title": _title_of(e.name, meta["head"]),
                    "mtime": meta["mtime"],
                    "size": meta["size"],
                    "approxWords": _approx_words(meta["head"], meta["size"]),
                    "excerpt": _excerpt_of(meta["head"]),
                })
            except Exception:
                continue
    return info


def _scan(force: bool = False) -> dict:
    now = time.time()
    if not force and _scan_cache["data"] and now - _scan_cache["ts"] < SCAN_TTL:
        return {**_scan_cache["data"], "cached": True}
    with _scan_lock:
        if not force and _scan_cache["data"] and now - _scan_cache["ts"] < SCAN_TTL:
            return {**_scan_cache["data"], "cached": True}
        cfg = _cfg()
        docs, roots = [], []
        budget = {"left": MAX_FILES}
        for r in cfg["roots"]:
            roots.append(_scan_root(r, budget, docs))
        docs.sort(key=lambda d: d["mtime"], reverse=True)
        data = {"roots": roots, "total": len(docs), "truncated": budget["left"] <= 0,
                "docs": docs, "cached": False}
        _scan_cache.update(ts=now, data=data)
        return data


def _inside_roots(abs_path: str, roots: List[str]) -> bool:
    target = os.path.normcase(os.path.abspath(abs_path))
    for r in roots:
        base = os.path.normcase(os.path.abspath(r))
        if target == base or target.startswith(base + os.sep):
            return True
    return False


# ---------------------------------------------------------------- jobs store
_jobs_lock = threading.Lock()


def _load_jobs() -> list:
    if JOBS_JSON.exists():
        try:
            j = json.loads(JOBS_JSON.read_text(encoding="utf-8"))
            return j if isinstance(j, list) else []
        except Exception:
            return []
    return []


def _save_jobs(jobs: list) -> None:
    tmp = JOBS_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs[:200], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(JOBS_JSON)


def _refresh_jobs(jobs: list) -> list:
    cfg = _cfg()
    changed = False
    alive = bool(_app_health(cfg).get("running"))
    for j in jobs:
        if j.get("done") or not j.get("id"):
            continue
        if not alive:
            # 服务没了 = 任务大概率断了（任务状态在 OpenMAIC 侧，重启后可能恢复，所以只是提示）
            if j.get("status") != "interrupted":
                j["status"] = "interrupted"
                j["message"] = "服务已停止"
                j["error"] = "OpenMAIC 已停止；重启服务后任务可能恢复，若长时间不动请重新生成"
                j["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                changed = True
            continue
        if j.get("status") == "interrupted":
            # 服务回来了：状态交回给下面的接口结果
            j["status"] = "running"
            j["message"] = "已恢复"
            changed = True
        try:
            d = _http_json(f"http://127.0.0.1:{cfg['port']}/api/generate-classroom/{j['id']}", timeout=6.0)
        except Exception:
            continue
        if j.get("error") and not d.get("error") and d.get("status"):
            j["error"] = None          # 之前打的「服务已停止」提示，服务侧已正常 → 清掉
            changed = True
        for k, src in (("status", "status"), ("progress", "progress"), ("message", "message")):
            if d.get(src) is not None and j.get(k) != d.get(src):
                j[k] = d[src]
                changed = True
        if d.get("result", {}).get("url"):
            j["url"] = d["result"]["url"]
            changed = True
        if d.get("error"):
            j["error"] = d["error"]
            changed = True
        if d.get("done"):
            j["done"] = True
            j["status"] = d.get("status", j.get("status"))
            changed = True
        j["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    if changed:
        _save_jobs(jobs)
    return jobs


# ---------------------------------------------------------------- schemas
class CfgPatch(BaseModel):
    roots: Optional[List[str]] = None


class GenerateIn(BaseModel):
    paths: List[str] = []
    mode: str = "merge"          # merge | each
    name: str = ""
    topic: str = ""              # 只给主题时用


# ---------------------------------------------------------------- routes
@router.get("/status")
def om_status():
    """OpenMAIC 服务状态 + 当前配置"""
    cfg = _cfg()
    st = _status()
    st["config"] = {"roots": cfg["roots"], "openmaic_dir": cfg["openmaic_dir"],
                    "port": cfg["port"], "relay_port": cfg["relay_port"]}
    return st


@router.post("/start")
def om_start():
    """按需拉起 OpenMAIC（转发 + 应用），最多等 150 秒"""
    return _start_service()


@router.post("/stop")
def om_stop():
    """停掉 OpenMAIC（应用 + 转发）"""
    return _stop_service()


@router.get("/config")
def om_config_get():
    return _cfg()


@router.put("/config")
def om_config_put(patch: CfgPatch):
    p = {}
    if patch.roots is not None:
        roots = [r.strip() for r in patch.roots if r and r.strip()]
        if not roots:
            raise HTTPException(status_code=400, detail="roots 不能为空")
        p["roots"] = roots
    _save_cfg(p)
    _scan_cache.update(ts=0.0, data=None)
    return _cfg()


@router.get("/docs")
def om_docs(q: str = "", root: str = "", refresh: int = 0):
    """本机文档索引（.md/.markdown/.txt）"""
    data = _scan(force=bool(refresh))
    docs = data["docs"]
    if root:
        docs = [d for d in docs if d["root"] == root]
    if q:
        ql = q.lower()
        docs = [d for d in docs if ql in d["title"].lower()
                or ql in d["relPath"].lower() or ql in d["excerpt"].lower()]
    return {"roots": data["roots"], "total": data["total"], "truncated": data["truncated"],
            "cached": data.get("cached", False), "count": len(docs), "docs": docs}


@router.get("/doc")
def om_doc(path: str = Query(...)):
    """取单篇全文（限 roots 内）"""
    cfg = _cfg()
    if not _inside_roots(path, cfg["roots"]):
        raise HTTPException(status_code=403, detail="路径不在允许的目录内")
    if Path(path).suffix.lower() not in TEXT_EXT:
        raise HTTPException(status_code=400, detail="只支持 .md / .markdown / .txt")
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {e}")
    return {"path": path, "chars": len(text), "text": text}


@router.post("/generate")
def om_generate(inp: GenerateIn):
    """生成课堂：mode=merge 合成一门；mode=each 每篇一门；只给 topic 时直接按主题生成"""
    cfg = _cfg()
    st = _app_health(cfg)
    if not st.get("running"):
        raise HTTPException(status_code=503, detail="OpenMAIC 未启动，请先点「启动服务」")

    targets = []
    if inp.topic.strip():
        targets = [(inp.topic.strip()[:60], None)]
    else:
        docs = {d["absPath"]: d for d in _scan()["docs"]}
        picked = [docs[p] for p in inp.paths if p in docs]
        if not picked:
            raise HTTPException(status_code=400, detail="没有选中有效文档（或文档已被移走）")
        if inp.mode == "each":
            targets = [(d["title"][:40], d) for d in picked]
        else:
            parts, used, dropped = [], 0, []
            for d in picked:
                try:
                    text = Path(d["absPath"]).read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    dropped.append(d["relPath"])
                    continue
                block = f"\n\n===== 文档：{d['relPath']} =====\n\n{text}"
                if used + len(block) > cfg["max_chars"]:
                    dropped.append(d["relPath"])
                    continue
                parts.append(block)
                used += len(block)
            name = inp.name.strip() or f"{picked[0]['title']} 等 {len(picked)} 篇材料"
            targets = [(name[:60], ("".join(parts), dropped, [d["relPath"] for d in picked]))]

    created = []
    for label, payload in targets:
        body = {
            "requirement": label,
            "language": "zh-CN",
            "enableWebSearch": False,
            "enableImageGeneration": False,
            "enableVideoGeneration": False,
            "enableTTS": False,
            "agentMode": "generate",
        }
        sources = []
        if isinstance(payload, tuple):
            text, dropped, sources = payload
            if text.strip():
                body["pdfContent"] = {"text": text, "images": []}
        elif isinstance(payload, dict):
            try:
                body["pdfContent"] = {"text": Path(payload["absPath"]).read_text(
                    encoding="utf-8", errors="ignore"), "images": []}
            except Exception:
                pass
            sources = [payload["relPath"]]
        try:
            resp = _http_json(f"http://127.0.0.1:{cfg['port']}/api/generate-classroom",
                              method="POST", payload=body, timeout=60.0)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"提交失败: {str(e)[:200]}")
        if not resp.get("success"):
            raise HTTPException(status_code=502, detail=str(resp)[:300])
        job = {
            "id": resp.get("jobId"), "label": label, "mode": inp.mode,
            "sources": sources, "status": resp.get("status", "queued"),
            "progress": 0, "message": "已入队", "url": None, "error": None, "done": False,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        created.append(job)

    with _jobs_lock:
        jobs = _load_jobs()
        jobs = created + jobs
        _save_jobs(jobs)
    return {"ok": True, "created": created, "jobs": created + _load_jobs()[len(created):]}


@router.get("/jobs")
def om_jobs(limit: int = Query(30, ge=1, le=200)):
    """任务列表（自动刷新未完成的）"""
    with _jobs_lock:
        jobs = _load_jobs()
        jobs = _refresh_jobs(jobs)
    return {"jobs": jobs[:limit], "total": len(jobs)}


@router.post("/jobs/clear")
def om_jobs_clear():
    """清掉已完成/失败的任务记录"""
    with _jobs_lock:
        jobs = [j for j in _load_jobs() if not j.get("done")]
        _save_jobs(jobs)
    return {"jobs": jobs}
