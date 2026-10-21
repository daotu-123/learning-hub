<#
.SYNOPSIS
    卸载 LearningHub Windows 服务。

.DESCRIPTION
    停止服务、删掉 sc.exe 配的失败恢复动作、删除服务注册表项
    （含 install-service.ps1 写进去的服务级 Environment 环境变量）。

    为什么要单独一个脚本而不是让人敲 sc.exe delete：
    `sc.exe delete` 只删服务主键，**不会**清掉 failure 动作配置——
    那也随服务键一起没了，但服务级 Environment 值同样随键消失，
    真正容易漏的是"停而不删"：只 Stop-Service 不 delete，
    下次装同名服务时 New-Service 会报已存在。

    本脚本幂等：服务不存在时直接提示并返回 0，不会报错。

.PARAMETER ServiceName
    服务名。默认 LearningHub。

.PARAMETER KeepLogs
    保留日志目录，不删 <LogDir>。

.EXAMPLE
    .\uninstall-service.ps1
    .\uninstall-service.ps1 -ServiceName LearningHub
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ServiceName = 'LearningHub',
    [switch]$KeepLogs
)

$ErrorActionPreference = 'Stop'

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "服务 $ServiceName 不存在，无需卸载。" -ForegroundColor Green
    return
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw '需要管理员权限。请用「以管理员身份运行 PowerShell」再执行本脚本。'
}

if (-not $PSCmdlet.ShouldProcess($ServiceName, '停止并删除 Windows 服务')) { return }

Write-Host "=== 卸载 $ServiceName ===" -ForegroundColor Cyan

# 1) 先停。停不掉也要继续删——SCM 会在 delete 时强杀。
if ($svc.Status -ne 'Stopped') {
    Write-Host '  停止服务...'
    try {
        Stop-Service -Name $ServiceName -Force -ErrorAction Stop
        # 等它真停，而不是等 SCM 返回（SCM 可能在进程退出前就返回）
        for ($i = 0; $i -lt 15; $i++) {
            if ((Get-Service -Name $ServiceName).Status -eq 'Stopped') { break }
            Start-Sleep -Seconds 1
        }
    }
    catch {
        Write-Warning "Stop-Service 失败：$($_.Exception.Message)——仍尝试删除。"
    }
}

# 2) 记住日志目录（删了服务键就取不到了）
$serviceRegPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"
$logDir = $null
try {
    $env = Get-ItemProperty -Path $serviceRegPath -Name 'Environment' -ErrorAction SilentlyContinue
    if ($env -and $env.Environment) {
        foreach ($line in $env.Environment) {
            if ($line -like 'HUB_SERVICE_LOG_DIR=*') {
                $logDir = $line.Substring('HUB_SERVICE_LOG_DIR='.Length)
            }
        }
    }
}
catch { }

# 3) 删除服务。注册表键（含 Environment）随之消失。
sc.exe @('delete', $ServiceName) 2>&1 | ForEach-Object { Write-Host "  $_" }
Start-Sleep -Seconds 2

# 4) 确认真没了
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Write-Warning "服务仍存在，可能是 SCM 尚未刷新。稍后执行：sc.exe query $ServiceName"
}
else {
    Write-Host "  服务已删除。" -ForegroundColor Green
}

# 5) 日志默认保留（里面可能有排查需要的历史），要删得显式说
if ($logDir -and -not $KeepLogs) {
    Write-Host "  日志目录保留在：$logDir"
    Write-Host "    （确认不再需要可手动删除；本脚本刻意不动它——卸载时误删日志会让「服务为什么停了」永远查不到）"
}

Write-Host "`n=== 完成 ===" -ForegroundColor Cyan
Write-Host "  数据目录未动（账号/会话/usage.db 都在里面）。"
Write-Host "  确认无残留进程：Get-Process LearningHubSvc -ErrorAction SilentlyContinue"
