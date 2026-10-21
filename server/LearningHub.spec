# -*- mode: python ; coding: utf-8 -*-
"""LearningHub 打包配置（M3-P1-1 修订）。

本次修订解决三件事：

1. **argon2-cffi 的 C 扩展必须显式声明**。
   argon2-cffi 25.x 的布局是「纯 Python 包 + 独立二进制发行包」：
       argon2-cffi（纯 Python）  Requires-Dist: argon2-cffi-bindings
       argon2-cffi-bindings（cp310-abi3-win_amd64）
           └─ _argon2_cffi_bindings/_ffi.pyd   ← 真正的 C 扩展
   导入链是静态的（low_level.py → _argon2_cffi_bindings → ._ffi），
   PyInstaller 的 modulegraph 通常能顺着走完。但「扩展模块位于一个**单独的
   distribution**、且包名以下划线开头」正是静态分析容易静默漏掉的那类结构：
   一旦哪天导入改成惰性/条件形式，**打包照样成功、构建零报错**，
   而故障只在首次登录时才炸（Argon2id 哈希不可用 → 建账号/登录全废）。
   因此这里用 hiddenimports 显式钉住，宁可重复收录也不靠推断。

2. **服务化需要一个 console 版 exe**。
   原配置 `console=False`（GUI 子系统）下进程**没有 stdout/stderr**，
   NSSM 的 stdout/stderr 重定向会得到两个永远为空的日志文件，
   排障时等于瞎子。因此一次构建产出两个 exe：
       LearningHub.exe        GUI   —— 桌面双击用，不弹黑窗
       LearningHubSvc.exe     CONSOLE —— 服务专用，日志有地方去
   两者代码完全相同，只是子系统不同；服务脚本用后者。

3. **datas 路径改用 SPECPATH**，不再依赖"当前工作目录恰好是 server/"。
   README 里写的构建命令确实在 server/ 下执行，但从别的 cwd 调用
   `pyinstaller path/to/LearningHub.spec` 时相对路径会静默解析错。

构建（在 server/ 目录下）：
    build-exe.bat
等价于：
    .venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean --distpath ..\\exe LearningHub.spec
产物直接输出到 <repo>/exe/。

**为什么 --distpath 必须写在命令行而不是本 spec 里**（本次踩过）：
PyInstaller 6 只在 spec 命名空间里注入只读的 `DISTPATH`，**并不会读 spec 里的
`distpath` 变量**——`CONF['distpath']` 在 exec spec 之前就已由命令行参数定好。
在 spec 里写 `distpath = ...` 会被静默忽略，产物照样落到 `./dist`，
而构建日志显示成功。曾经靠 README 里一条手工 `copy` 把产物搬去 exe/，
那条命令漏执行时 exe/ 里躺着的就是旧版：本次重打就发现 exe/ 的产物停在
10-18，落后代码两个里程碑（没有 /health 探针、不认 HUB_PORT/HUB_DATA_DIR）。
所以落点由 build-exe.bat 钉死，不依赖任何人记得敲 copy。
"""

from pathlib import Path

ICON = str(Path(SPECPATH) / '..' / 'exe' / 'learninghub_icon.ico')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # SPECPATH = spec 文件所在目录（PyInstaller 注入的全局变量）。
    # 用绝对路径拼，避免相对路径随 cwd 漂移。
    datas=[
        (str(Path(SPECPATH) / 'hub_web'), 'hub_web'),
        (str(Path(SPECPATH) / 'web_dist'), 'web_dist'),
    ],
    hiddenimports=[
        # argon2-cffi 的 C 扩展（独立发行包 argon2-cffi-bindings）。
        # 收包名 + 具体扩展模块两层：只写包名时，若 __init__ 的导入方式变化
        # 仍可能漏掉 _ffi；两层都写则任何一层生效即可。
        '_argon2_cffi_bindings',
        '_argon2_cffi_bindings._ffi',
        # 兜底：argon2 纯 Python 包自身的子模块（profiles / _password_hasher 等）。
        # 这些本会被 modulegraph 自动收录，写上只为在上面那条链断裂时仍可用。
        'argon2',
        'argon2.low_level',
        'argon2.profiles',
        'argon2._password_hasher',
        'argon2._legacy',
        'argon2._utils',
        'argon2.exceptions',
    ],
    hookspath=[],
    hooksconfig={},
    # 把标准流固定成 UTF-8。环境变量对 frozen exe 无效，只能走 runtime hook。
    runtime_hooks=[str(Path(SPECPATH) / 'pyi_rth_utf8_io.py')],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# ---- 桌面版：GUI 子系统（双击运行不弹控制台窗口）--------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='学习中枢服务',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)


# ---- 服务版：CONSOLE 子系统 ----------------------------------------
# 与桌面版同一份 pyz，只改 console 与 name。
# 必须 console=True：Windows 服务（NSSM/sc.exe）要把 stdout/stderr 重定向到
# 日志文件，而 GUI 子系统进程根本没有这两个句柄，重定向会得到两个空文件，
# 排障时等于瞎子。
exe_svc = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LearningHubSvc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)


# ---- 管理版：CONSOLE 子系统 ----------------------------------------
# 为什么需要第三个 exe：部署机上**没有 Python**（这正是打包的动机），
# 而建账号唯一的入口是 `python manage.py set-password`。没有它，
# 部署文档里"从零到可用"的第一步就卡住，只能回开发机上建好再拷
# account.json 过去——那是把密钥材料当普通文件搬运，不如直接给个 exe。
# 同时也是 argon2 C 扩展的验收载体：这个 exe 跑一次 set-password，
# 就能证明哈希在打包后真的可用（见 docs/deploy-windows.md 的验收节）。
#
# 单独的 Analysis：入口脚本不同（manage.py 而非 main.py），
# 依赖图也不一样（不需要 uvicorn/fastapi 那一堆）。
a_mgmt = Analysis(
    ['manage.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        '_argon2_cffi_bindings',
        '_argon2_cffi_bindings._ffi',
    ],
    hookspath=[],
    hooksconfig={},
    # 把标准流固定成 UTF-8。环境变量对 frozen exe 无效，只能走 runtime hook。
    runtime_hooks=[str(Path(SPECPATH) / 'pyi_rth_utf8_io.py')],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz_mgmt = PYZ(a_mgmt.pure)

exe_mgmt = EXE(
    pyz_mgmt,
    a_mgmt.scripts,
    a_mgmt.binaries,
    a_mgmt.datas,
    [],
    name='LearningHubManage',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
