# -*- coding: utf-8 -*-
"""按注册顺序枚举 FastAPI 全部路由（METHOD PATH），用于重构前后比对。

用法：
    python dump_routes.py            # 打印到 stdout
    python dump_routes.py > before.txt

为什么需要它：本版本 FastAPI 的 include_router 会生成 `_IncludedRouter` 包装对象，
直接遍历 `app.routes` 看不到子路由；而静态页 `/hub` 与 `/hub/{path}` 这类
「精确路径 + 通配路径」的组合对注册顺序敏感，拆 routers/ 时必须逐条比对。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def walk(routes):
    out = []
    for r in routes:
        cls = type(r).__name__
        if cls == "_IncludedRouter":
            out += walk(r.original_router.routes)
        elif hasattr(r, "methods") and hasattr(r, "path"):
            for m in sorted(r.methods):
                if m in ("HEAD", "OPTIONS"):
                    continue
                out.append((m, r.path))
    return out


def dump(app) -> list:
    return walk(app.routes)


if __name__ == "__main__":
    import main

    rows = dump(main.app)
    for m, p in rows:
        print(f"{m} {p}")
    print(f"# total={len(rows)}", file=sys.stderr)
