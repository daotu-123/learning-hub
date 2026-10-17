# -*- coding: utf-8 -*-
"""学习中枢图标总处理：去水印（列复制法）→ 母版 PNG → ICO → Android 自适应前景层"""
from PIL import Image
import os

SRC = r"c:\Users\Administrator\WorkBuddy\2026-10-12-12-31-36\generated-images\App_icon_design_for_a_study_pr_2026-10-17T05-49-57.png"
OUT_DIR = r"E:\agent\androd-app\exe"
RES = r"E:\agent\androd-app\hub-app\app\src\main\res"

im = Image.open(SRC).convert("RGB")
W, H = im.size
px = im.load()

# ---------- 1) 定位右下角水印 ----------
rx0, ry0 = int(W * 0.70), int(H * 0.86)
minx, miny, maxx, maxy = W, H, 0, 0
for y in range(ry0, H):
    for x in range(rx0, W):
        r, g, b = px[x, y]
        if 0.299 * r + 0.587 * g + 0.114 * b > 90:
            minx = min(minx, x); maxx = max(maxx, x)
            miny = min(miny, y); maxy = max(maxy, y)
print("watermark bbox:", (minx, miny, maxx, maxy))

# ---------- 2) 水平镜像覆盖：从左下角同款区域镜像 ----------
# 设计的左下角与右下角结构一致（瓷砖暗边+黑底+软阴影，无图案），
# 水平镜像可完整保留渐变与抗锯齿，比任何插值都准
pad = 10
x0, x1 = max(0, minx - pad), min(W - 1, maxx + pad)
y0, y1 = max(0, miny - pad), min(H - 1, maxy + pad)
for y in range(y0, y1 + 1):
    for x in range(x0, x1 + 1):
        px[x, y] = px[W - 1 - x, y]
residual = sum(1 for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
               if 0.299 * px[x, y][0] + 0.587 * px[x, y][1] + 0.114 * px[x, y][2] > 90)
print("residual bright pixels:", residual)

# ---------- 3) 母版 PNG（不透明，供 ICO/预览） ----------
os.makedirs(OUT_DIR, exist_ok=True)
master = os.path.join(OUT_DIR, "learninghub_icon_1024.png")
im.save(master)
print("master:", master)

# ---------- 4) ICO（七尺寸，不透明） ----------
ico = os.path.join(OUT_DIR, "learninghub_icon.ico")
im.save(ico, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ico:", ico, os.path.getsize(ico), "bytes")

# ---------- 5) Android 自适应前景层：亮度转 alpha（瓷砖外纯黑变透明） ----------
fg = im.convert("RGBA")
fpx = fg.load()
for y in range(H):
    for x in range(W):
        r, g, b, a = fpx[x, y]
        lum = max(r, g, b)
        alpha = lum / 12.0
        if alpha > 1.0:
            alpha = 1.0
        fpx[x, y] = (r, g, b, int(alpha * 255))

sizes = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}
for den, s in sizes.items():
    d = os.path.join(RES, "drawable-" + den)
    os.makedirs(d, exist_ok=True)
    fg.resize((s, s), Image.LANCZOS).save(os.path.join(d, "ic_launcher_foreground.png"))
    print("android foreground:", den, s)

# ---------- 6) 取样瓷砖边缘色（作为自适应背景色） ----------
samples = []
for x in range(W // 2 - 40, W // 2 + 40, 8):
    for y in range(0, H):
        if max(px[x, y]) > 6:
            samples.append(px[x, y]); break
for y in range(H // 2 - 40, H // 2 + 40, 8):
    for x in range(0, W):
        if max(px[x, y]) > 6:
            samples.append(px[x, y]); break
samples.sort(key=lambda c: sum(c))
bg = samples[len(samples) // 2] if samples else (16, 19, 24)
bg_hex = "#%02x%02x%02x" % bg
print("tile edge color ->", bg_hex)
with open(os.path.join(OUT_DIR, "bg_color.txt"), "w") as f:
    f.write(bg_hex)
print("done")
