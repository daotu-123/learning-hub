# -*- coding: utf-8 -*-
"""
Learning Hub: vault_reader
读取 Obsidian 数据源的只读解析器
- 日记 checkbox 任务 / 积分 / 进度行
- DeepTutor 输出目录（反馈/文章/博主/周记/月记）
- 收藏库统计（depot/class）
只读，绝不写 vault。
"""
import re
import time
import datetime
from pathlib import Path
from typing import Optional, List, Dict

# M1a：vault 根改由 config 单一来源（原为本文件硬编码，与 main.py / openmaic.py 三处重复）
from config import FAVORITES_ROOT, HERMES_DIR, OBSIDIAN_VAULT

DIARY_ROOT = OBSIDIAN_VAULT / "日记"
DEEPTUTOR_DIR = OBSIDIAN_VAULT / "DeepTutor"
CLASS_DIR = FAVORITES_ROOT
HERMES_SCRIPTS = HERMES_DIR

# 收藏库各平台目录（frontmatter 链接字段名不同）
LIBRARY_ROOTS = [
    ("抖音收藏", CLASS_DIR / "抖音收藏", "source_url"),
    ("小红书收藏", CLASS_DIR / "小红书收藏", "url"),
    ("知乎收藏", CLASS_DIR / "知乎收藏", "url"),
    ("B站收藏", CLASS_DIR / "B站收藏", "url"),
    ("LLM-Wiki", CLASS_DIR / "LLM-Wiki", ""),
]

# library_stats 全量扫描缓存（1w+ 文件，TTL 10 分钟）
_lib_cache = {"ts": 0.0, "data": None}
LIB_CACHE_TTL = 600.0

CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s*(.+)$")
SCORE_INLINE_RE = re.compile(r"[（(]\s*(\d+)\s*[）)]")
PLAN_ITEM_RE = re.compile(r"^\s*([^【（：:]+?)\s*[【（]\s*(\d+)\s*[）】]\s*[:：]\s*(.*)$")
TAGS_RE = re.compile(r"^tags:\s*\[(.*?)\]$")


def _month_dir_name(d: datetime.date) -> str:
    return f"{str(d.year)[2:]}年{d.month}月"


def diary_path(date_str: str) -> Optional[Path]:
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        return None
    month_dir = DIARY_ROOT / _month_dir_name(d)
    if not month_dir.exists():
        return None
    cand = month_dir / f"{date_str}.md"
    return cand if cand.exists() else None


def read_diary(date_str: str) -> Optional[str]:
    p = diary_path(date_str)
    if p is None:
        return None
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def parse_checkboxes(text: str) -> List[Dict]:
    """解析全部 checkbox 任务行：- [x] 1.任务名（20）"""
    out = []
    for line in text.splitlines():
        m = CHECKBOX_RE.match(line)
        if not m:
            continue
        done = m.group(1).strip().lower() == "x"
        rest = m.group(2).strip()
        score = None
        sm = SCORE_INLINE_RE.search(rest)
        if sm:
            score = int(sm.group(1))
        out.append({"done": done, "title": rest, "score": score})
    return out


def parse_plan_progress(text: str) -> Dict[str, Dict]:
    """解析「其余计划选项」区的渐进计划进度行：
    武忠祥基础【2】：31、32  →  {"武忠祥基础": {"step":2, "progress":"31、32", "done":bool}}"""
    out = {}
    m = re.search(r"##\s*其余计划选项(.*?)(?=\n## |\Z)", text, re.S)
    if not m:
        return out
    for line in m.group(1).splitlines():
        pm = PLAN_ITEM_RE.match(line)
        if not pm:
            continue
        name = pm.group(1).strip()
        step = int(pm.group(2))
        prog = pm.group(3).strip()
        done = any(mk in prog for mk in ("✅", "☑️", "✔", "[x]", "[X]", "完成"))
        out[name] = {"step": step, "progress": prog, "done": done}
    return out


def extract_tags(text: str) -> List[str]:
    """提取 frontmatter tags 行"""
    m = TAGS_RE.search(text)
    if not m:
        return []
    return [t.strip().strip('"').strip("'") for t in m.group(1).split(",") if t.strip()]


def diary_summary(date_str: str) -> Optional[Dict]:
    """单日日记摘要：checkbox 统计 + 积分 + 进度行 + tags"""
    text = read_diary(date_str)
    if text is None:
        return None
    tasks = parse_checkboxes(text)
    done_tasks = [t for t in tasks if t["done"]]
    score_total = sum(t["score"] for t in done_tasks if t["score"])
    return {
        "date": date_str,
        "exists": True,
        "tasks_total": len(tasks),
        "tasks_done": len(done_tasks),
        "score": score_total,
        "tags": extract_tags(text),
        "plans": parse_plan_progress(text),
        "has_feedback": bool(re.search(r"##\s*反馈闭环", text)),
    }


def overview(days: int = 30) -> Dict:
    """打卡热力图 + 积分趋势数据（不含今日则全量）"""
    today = datetime.date.today()
    dates, heat = [], []
    for i in range(days):
        d = today - datetime.timedelta(days=days - 1 - i)
        ds = d.isoformat()
        s = diary_summary(ds)
        dates.append(ds)
        if s is None:
            heat.append({"date": ds, "tasks_done": 0, "tasks_total": 0, "score": 0, "exists": False})
        else:
            heat.append({"date": ds, "tasks_done": s["tasks_done"], "tasks_total": s["tasks_total"],
                         "score": s["score"], "exists": True})
    return {"days": days, "data": heat}


def plans_progress(days: int = 7) -> Dict:
    """最近 N 天各计划项进度演进：{计划名: [{"date":..,"progress":..,"done":..}, ...]}"""
    today = datetime.date.today()
    series: Dict[str, List] = {}
    for i in range(days):
        d = today - datetime.timedelta(days=days - 1 - i)
        ds = d.isoformat()
        text = read_diary(ds)
        if not text:
            continue
        for name, info in parse_plan_progress(text).items():
            series.setdefault(name, []).append({
                "date": ds,
                "progress": info["progress"],
                "done": info["done"],
            })
    # 无进度的日期补空，保证时间轴连续
    for name in series:
        filled = []
        for i in range(days):
            d = today - datetime.timedelta(days=days - 1 - i)
            ds = d.isoformat()
            hit = next((x for x in series[name] if x["date"] == ds), None)
            filled.append(hit or {"date": ds, "progress": "", "done": False})
        series[name] = filled
    return {"days": days, "series": series}


# ---------------------------------------------------------------- DeepTutor 目录
def deeptutor_notes(date_str: str) -> Dict:
    """某日 DeepTutor 输出文件清单：反馈/文章/博主/昨日习题/周记/月记"""
    out: Dict[str, List] = {}
    if not DEEPTUTOR_DIR.exists():
        return out

    def collect(sub: str, pat: str, kind: str):
        d = DEEPTUTOR_DIR / sub
        if not d.exists():
            return
        items = sorted(d.glob(pat))
        if items:
            out[kind] = [{"name": f.name, "path": str(f)} for f in items]

    collect("每日反馈", f"{date_str}.md", "反馈")
    collect("每日文章", f"{date_str}.md", "文章")
    collect("每日博主", f"{date_str}.md", "博主")
    collect("昨日习题", f"{date_str}.md", "习题")
    return out


def feedback_latest(n: int = 5) -> List[Dict]:
    """最近 N 篇每日反馈（标题 + 重点速览 callout 摘要）"""
    d = DEEPTUTOR_DIR / "每日反馈"
    if not d.exists():
        return []
    files = sorted(d.glob("*.md"), reverse=True)[:n]
    out = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # 提取 🎯 今日重点速览 callout 内容
        m = re.search(r">\s*\[!important\][^\n]*\n(.*?)(?=\n## |\Z)", text, re.S)
        digest = ""
        if m:
            digest = "\n".join(
                line.strip() for line in m.group(1).splitlines()
                if line.strip().startswith(">")
            ).strip()
        out.append({"name": f.name, "date": f.stem, "digest": digest[:500]})
    return out


def library_stats() -> Dict:
    """收藏库统计：各平台篇数 + 最近文件（带 TTL 缓存，全量扫描 1w+ 文件较慢）"""
    now = time.time()
    if _lib_cache["data"] and now - _lib_cache["ts"] < LIB_CACHE_TTL:
        return _lib_cache["data"]
    stats = []
    for label, root, _ in LIBRARY_ROOTS:
        if not root.exists():
            stats.append({"name": label, "count": 0, "recent": []})
            continue
        files = list(root.rglob("*.md"))
        recent = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        stats.append({
            "name": label,
            "count": len(files),
            "recent": [{"name": f.name, "path": str(f)} for f in recent],
        })
    result = {"roots": stats, "total": sum(s["count"] for s in stats)}
    _lib_cache["data"] = result
    _lib_cache["ts"] = now
    return result
