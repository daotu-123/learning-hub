<#
.SYNOPSIS
    安装 LearningHub 为 Windows 服务（开机自启 + 崩溃自动重启 + 日志落文件）。

.DESCRIPTION
    把 <repo>\exe\LearningHubSvc.exe 注册为 Windows 服务。

    四个硬性要求的实现方式，以及为什么这么选：

    1) 开机自启
       StartType = Automatic，并尽量设为 delayed-auto（等网络就绪后再起，
       避免开机瞬间 vault 在网络盘上还没挂好导致首启失败）。delayed-auto
       只能由 `sc.exe config start= delayed-auto` 设置，New-Service 不支持，
       所以分两步走。

    2) 崩溃自动重启
       sc.exe failure 配 5s/30s/60s 三次重启。注意这是"崩溃"语义：
       进程退出或返回非零才触发。**进程假死（不退出但不响应）sc.exe 检测
       不到**，那需要看门狗；本脚本不引入 NSSM 这类新依赖，限制写进
       docs/deploy-windows.md 的「已知限制」。

    3) stdout/stderr 落文件
       服务跑在 Session 0 没有控制台，进程标准流无处可去。这里**不用**
       `cmd /c "exe > log 2>&1"` 包装：SCM 的 STOP 会发给 cmd.exe 而不是
       exe，停服务时大概率留下占着端口的孤儿进程。
       改为让 exe 自己 tee：设置 HUB_SERVICE_LOG_DIR，打包时内置的 runtime
       hook（server/pyi_rth_utf8_io.py）会把标准流同时写进
         <LogDir>\service-stdout.log
         <LogDir>\service-stderr.log
       uvicorn 的 access/error 日志本就由 logging_setup 写进
       <DataDir>\server.log（2MB×3 轮转、UTF-8、token/sig 已打码），
       两者互补不重叠。

    4) 以指定账号运行
       -ServiceAccount 指定。默认 LocalSystem。若 vault 在网络盘或另一用户
       目录下，必须指定有读取权限的账号，否则服务起得来但读不到日记照片。

    数据目录必填：不指定就等于让账号写进仓库内默认目录——P0-3 给 manage.py
    加的防呆拦的就是这个，装服务时同一个坑值得再拦一次。

.PARAMETER ExePath
    服务 exe。默认取 <repo>\exe\LearningHubSvc.exe（脚本在 <repo>\deploy\ 下）。

.PARAMETER ServiceName
    服务内部名。默认 LearningHub。

.PARAMETER DataDir
    数据目录（HUB_DATA_DIR）。必填。

.PARAMETER VaultDir
    Obsidian vault（HUB_VAULT）。不填用 exe 内默认值。

.PARAMETER Port
    监听端口（HUB_PORT）。默认 8637。

.PARAMETER LogDir
    stdout/stderr 日志目录（HUB_SERVICE_LOG_DIR）。默认 <DataDir>\logs。

.PARAMETER ServiceAccount
    运行账号。默认 LocalSystem。非 LocalSystem 时必须给 -ServicePassword。

.PARAMETER ServicePassword
    服务账号口令（SecureString）。

.PARAMETER TrustedProxies
    受信反代 IP/CIDR（HUB_TRUSTED_PROXIES）。默认 127.0.0.1 —— 只信本机
    回环上跑的 Caddy。反代不在本机时必须改，否则限流会把整个代理当一个 IP。

.PARAMETER NoStart
    装完不启动（无人值守场景）。

.PARAMETER WhatIfPreflight
    只打印将要执行的动作，不真正安装。用于在非管理员环境预检。

.EXAMPLE
    .\install-service.ps1 -DataDir D:\LearningHub\data -VaultDir E:\notes

.EXAMPLE
    .\install-service.ps1 -DataDir D:\LH\data -VaultDir E:\notes `
        -ServiceAccount '.\LearningHubSvc' `
        -ServicePassword (Read-Host -AsSecureString)

.EXAMPLE
    .\install-service.ps1 -DataDir D:\LH\data -WhatIfPreflight
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ExePath,
    [string]$ServiceName = 'LearningHub',
    [string]$DisplayName = '学习中枢 Learning Hub',
    [string]$Description = '学习中枢同步服务（工作台 / 机械题库后端）',
    [string]$DataDir,
    [string]$VaultDir,
    [int]$Port = 8637,
    [string]$LogDir,
    [string]$ServiceAccount = 'LocalSystem',
    [SecureString]$ServicePassword,
    [string]$TrustedProxies = '127.0.0.1',
    [switch]$NoStart,
    [switch]$WhatIfPreflight
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- 路径推导
if (-not $ExePath) {
    # 脚本位于 <repo>\deploy\，exe 位于 <repo>\exe\
    $repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $ExePath = Join-Path $repo 'exe\LearningHubSvc.exe'
}
if (-not (Test-Path $ExePath)) {
    throw "找不到服务 exe：$ExePath`n请先运行 server\build-exe.bat 打包。服务必须用 console 版 LearningHubSvc.exe——GUI 版没有标准流，日志会是空的。"
}
$ExePath = (Resolve-Path $ExePath).Path

if (-not $DataDir) {
    throw '必须指定 -DataDir（对应 HUB_DATA_DIR）。不指定就等于让账号写进仓库内默认目录——P0-3 给 manage.py 加的防呆拦的就是这个。'
}
$DataDir = [System.IO.Path]::GetFullPath($DataDir)
if (-not $LogDir) { $LogDir = Join-Path $DataDir 'logs' }
$LogDir = [System.IO.Path]::GetFullPath($LogDir)

# ---------------------------------------------------------------- 预检
Write-Host '=== 安装前预检 ===' -ForegroundColor Cyan
Write-Host ("  服务名     : {0}" -f $ServiceName)
Write-Host ("  exe        : {0}" -f $ExePath)
Write-Host ("  数据目录   : {0}" -f $DataDir)
Write-Host ("  日志目录   : {0}" -f $LogDir)
Write-Host ("  vault      : {0}" -f $(if ($VaultDir) { $VaultDir } else { '(用 exe 内默认值)' }))
Write-Host ("  端口       : {0}" -f $Port)
Write-Host ("  运行账号   : {0}" -f $ServiceAccount)
Write-Host ("  受信反代   : {0}" -f $TrustedProxies)

try {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    $probe = Join-Path $DataDir '.svc-write-probe'
    [System.IO.File]::WriteAllText($probe, 'ok')
    Remove-Item $probe -Force
    Write-Host '  目录可写   : 是' -ForegroundColor Green
}
catch {
    throw "数据目录或日志目录不可写：$($_.Exception.Message)"
}

if ($VaultDir -and -not (Test-Path $VaultDir)) {
    Write-Warning "vault 路径不存在：$VaultDir（服务仍会安装，但日记/照片类功能不可用）"
}

# ---------------------------------------------------------------- 环境变量
# sc.exe 的 binPath 只是一行命令行，塞不进环境变量。写进服务的注册表
# Environment（REG_MULTI_SZ）——SCM 启动服务进程时会应用它。
# 不用 setx：那会改用户级/机器级环境，影响面远超本服务，且卸载时清不干净。
$envPairs = [ordered]@{
    'HUB_DATA_DIR'        = $DataDir
    'HUB_PORT'            = "$Port"
    'HUB_SERVICE_LOG_DIR' = $LogDir
    'HUB_TRUSTED_PROXIES' = $TrustedProxies
    'PYTHONIOENCODING'    = 'utf-8'
    'PYTHONUTF8'          = '1'
}
if ($VaultDir) { $envPairs['HUB_VAULT'] = $VaultDir }
$serviceRegPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"

# sc.exe 的文档写法是 `binPath= <值>`（等号后带空格）。用参数数组分别传
# `binPath=` 与值，比拼成一整串再交给 cmd.exe /c 可靠得多——后者会被
# 嵌套引号吃掉。此处不打印含口令的命令。
$scDelayed = @('config', $ServiceName, 'start=', 'delayed-auto')
$scDesc    = @('description', $ServiceName, $Description)
$scFailure = @('failure', $ServiceName, 'reset=', '86400',
               'actions=', 'restart/5000/restart/30000/restart/60000')

if ($WhatIfPreflight) {
    Write-Host "`n=== 预检模式：以下动作不会真正执行 ===" -ForegroundColor Magenta
    Write-Host ("  New-Service -Name {0} -BinaryPathName '{1}' -StartupType Automatic" -f $ServiceName, $ExePath)
    Write-Host ("  sc.exe {0}" -f ($scDelayed -join ' '))
    Write-Host ("  sc.exe {0}" -f ($scDesc -join ' '))
    Write-Host ("  sc.exe {0}" -f ($scFailure -join ' '))
    if ($ServiceAccount -ne 'LocalSystem') {
        Write-Host ("  sc.exe config {0} obj= '{1}' password= ***" -f $ServiceName, $ServiceAccount)
    } else {
        Write-Host '  (运行账号用默认 LocalSystem，无需 sc.exe obj=)'
    }
    Write-Host "  注册表 $serviceRegPath 的 Environment："
    foreach ($k in $envPairs.Keys) { Write-Host ("    {0}={1}" -f $k, $envPairs[$k]) }
    Write-Host "`n（预检模式未做任何改动）"
    return
}

# ---------------------------------------------------------------- 权限与已存服务
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw '需要管理员权限。请用「以管理员身份运行 PowerShell」再执行本脚本。'
}

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "`n服务已存在，先停止并删除旧注册..." -ForegroundColor Yellow
    if ($existing.Status -ne 'Stopped') {
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }
    sc.exe @('delete', $ServiceName) | Out-Null
    Start-Sleep -Seconds 2
}

if (-not $PSCmdlet.ShouldProcess("$ServiceName -> $ExePath", '创建 Windows 服务')) { return }

# ---------------------------------------------------------------- 安装
Write-Host "`n=== 安装 ===" -ForegroundColor Cyan

# 1) 创建服务
New-Service -Name $ServiceName -BinaryPathName $ExePath -DisplayName $DisplayName -StartupType Automatic | Out-Null
Write-Host '  [1/5] New-Service 完成' -ForegroundColor Green

# 2) delayed-auto：等网络就绪后再起（vault 在网络盘时关键）
#    失败不阻塞——退化成普通 Automatic 也能用，只是开机首启可能赶在网盘挂载前。
try {
    & sc.exe @scDelayed 2>&1 | ForEach-Object { Write-Host "        $_" }
    Write-Host '  [2/5] 启动类型设为 delayed-auto' -ForegroundColor Green
}
catch {
    Write-Warning "设 delayed-auto 失败（$($_.Exception.Message)），保持 Automatic。"
}

# 3) 描述
try {
    & sc.exe @scDesc 2>&1 | Out-Null
    Write-Host '  [3/5] 描述已写' -ForegroundColor Green
}
catch { Write-Warning '写描述失败（不影响功能）。' }

# 4) 崩溃自动重启
try {
    & sc.exe @scFailure 2>&1 | ForEach-Object { Write-Host "        $_" }
    Write-Host '  [4/5] 失败恢复动作已配（5s/30s/60s 三次重启）' -ForegroundColor Green
}
catch { Write-Warning "配失败恢复动作失败：$($_.Exception.Message)" }

# 5) 运行账号
if ($ServiceAccount -ne 'LocalSystem') {
    if (-not $ServicePassword) {
        throw '指定了 -ServiceAccount 就必须给 -ServicePassword（服务账号口令不会从交互会话继承）。'
    }
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ServicePassword))
    try {
        & sc.exe @('config', $ServiceName, 'obj=', $ServiceAccount, 'password=', $plain) 2>&1 |
            ForEach-Object { Write-Host "        $_" }
        Write-Host "  [5/5] 运行账号已设为 $ServiceAccount" -ForegroundColor Green
    }
    finally {
        $plain = $null
    }
} else {
    Write-Host '  [5/5] 运行账号用默认 LocalSystem' -ForegroundColor Green
}

# ---------------------------------------------------------------- 环境变量落注册表
try {
    New-Item -Path $serviceRegPath -Force | Out-Null
    $multi = @()
    foreach ($k in $envPairs.Keys) { $multi += ("{0}={1}" -f $k, $envPairs[$k]) }
    $multi += ''    # REG_MULTI_SZ 需要以空串结尾
    Set-ItemProperty -Path $serviceRegPath -Name 'Environment' -Value $multi -Type MultiString -Force
    Write-Host '  服务级环境变量已写入注册表' -ForegroundColor Green
}
catch {
    Write-Warning "写服务级环境变量失败：$($_.Exception.Message)`n服务仍会启动，但用的是 exe 内默认路径——请改用 -DataDir 指向正确目录后重装。"
}

# ---------------------------------------------------------------- 收尾
Write-Host "`n=== 完成 ===" -ForegroundColor Cyan
Write-Host ("  当前状态 : {0}" -f (Get-Service -Name $ServiceName).Status)
Write-Host "  启动     : Start-Service $ServiceName"
Write-Host "  查状态   : Get-Service $ServiceName"
Write-Host ("  看标准流 : Get-Content '{0}\service-stdout.log' -Wait" -f $LogDir)
Write-Host ("  看服务日志: Get-Content '{0}\server.log' -Tail 50 -Wait" -f $DataDir)
Write-Host "  卸载     : .\uninstall-service.ps1 -ServiceName $ServiceName"

if (-not $NoStart) {
    $answer = Read-Host "`n现在启动服务吗？[Y/n]"
    if ($answer -match '^[Yy]?$') {
        Start-Service -Name $ServiceName
        Start-Sleep -Seconds 3
        Write-Host ("  启动后状态: {0}" -f (Get-Service -Name $ServiceName).Status) -ForegroundColor Green
        Write-Host "  若启动失败，先看 service-stderr.log 与 server.log。"
    }
}
