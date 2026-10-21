<#
.SYNOPSIS
    LearningHub 部署机防火墙规则：只放行 80/443，并主动确认 8637 未对公网暴露。

.DESCRIPTION
    三条入站规则 + 一次深度检查。

    放行：
      TCP 80   —— Caddy 的 HTTP→HTTPS 跳转，以及 Let's Encrypt 的
                 HTTP-01 验证（自动签发/续期证书要从公网访问 80）。
                 没有 80 就没有自动 TLS，所以这条不是可选项。
      TCP 443  —— Caddy 的 HTTPS，唯一对外服务入口。
      TCP 22   —— 仅当显式加 -OpenSSH。默认不开：VPS 用面板/串口/云厂商
                 自带终端管理时不需要它，开着只是多一个被扫的面。

    按需：
      TCP 8637 —— **永远不放行**。服务只应监听 127.0.0.1 由同机 Caddy 回源，
                 或绑内网网卡给手机直连。暴露到公网等于绕过 Caddy 的 TLS
                 与访问日志，且服务端会把每个直连 IP 当客户端
                 （那时 HUB_TRUSTED_PROXIES 里的 127.0.0.1 就不够了）。

    ------------------------------------------------------------------
    **深度检查为什么是五条判定而不是一条**（这一节是实测踩出来的）：

    初版只按端口扫，报出 43 条"放行 8637"的规则，差点造成一次误判。
    这 43 条确实满足「TCP + LocalPort=Any + RemoteAddress=Any」，
    但**全部带程序/服务作用域**（raserver.exe、svchost.exe、WUDFHost.exe…），
    只对那一个程序生效，跟 LearningHubSvc.exe 毫无关系。
    真正危险的「无作用域 + 任意 TCP 端口 + 任意来源」在当时是 0 条。

    所以判定必须是五条同时成立才算是真的暴露：
        1) Direction=Inbound、Enabled、Action=Allow
        2) Protocol = TCP          （不过滤会把 162 条 UDP 规则算进来）
        3) LocalPort 覆盖 8637     （明确写 / 段式 / Any）
        4) RemoteAddress 覆盖公网 （Any，或公网段）
        5) **无程序作用域**，或作用域指向 LearningHubSvc.exe
    只有第 5 条能把"给 raserver 开的端口"和"给任意程序开的端口"分开。
    少这一条，这个检查就会持续产出假警报——而假警报比不报警更糟：
    它会训练使用者直接忽略输出。

    已知代价：逐规则关联 PortFilter 很慢（本机实测约 1-2 分钟）。
    这是一次性部署校验，可接受；只想建规则不想等，加 -NoDeepScan。

    需要管理员权限（Apply / Remove）。

.PARAMETER Action
    Apply  创建规则（并跑深度检查）
    Remove 删除本脚本创建的规则
    Show   只显示当前状态，不做任何改动（深度检查需要读全表，同样要等）

.PARAMETER OpenSSH
    额外放行 TCP 22。

.PARAMETER ServiceName
    规则名前缀，避免与机器上其它规则重名。默认 LearningHub。

.PARAMETER NoDeepScan
    跳过 8637 深度检查（只建/删规则）。

.EXAMPLE
    .\firewall-rules.ps1 -Action Show
    .\firewall-rules.ps1 -Action Apply
    .\firewall-rules.ps1 -Action Apply -OpenSSH
    .\firewall-rules.ps1 -Action Apply -NoDeepScan
    .\firewall-rules.ps1 -Action Remove
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Apply', 'Remove', 'Show')]
    [string]$Action = 'Show',
    [switch]$OpenSSH,
    [string]$ServiceName = 'LearningHub',
    [switch]$NoDeepScan
)

$ErrorActionPreference = 'Stop'

$SERVICE_PORT = 8637
$SERVICE_EXE = 'LearningHubSvc.exe'

function Test-Admin {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ---------------------------------------------------------------------
#  深度检查：找出「真的会把 8637 暴露给公网」的规则。
#  五条判定见文件头说明，这里逐条落实。
# ---------------------------------------------------------------------
function Find-PublicExposureOfPort([int]$Port, [string]$OwnExeName) {
    $found = New-Object System.Collections.ArrayList

    Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow -ErrorAction SilentlyContinue |
        ForEach-Object {
            $rule = $_

            # (2) 协议必须是 TCP —— 不过滤会把 162 条 UDP 规则算进来
            $pf = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule -ErrorAction SilentlyContinue
            if (-not $pf) { return }
            if ("$($pf.Protocol)".ToUpper() -ne 'TCP') { return }

            # (3) 端口覆盖：明确写 / 段式 / Any
            $portCovers = $false
            $spec = "$($pf.LocalPort)"
            if ($spec -eq 'Any') {
                $portCovers = $true
            } else {
                foreach ($part in ($spec -split ',')) {
                    $t = $part.Trim()
                    if ($t -eq "$Port") { $portCovers = $true; break }
                    if ($t -match '^(\d+)-(\d+)$' -and $Port -ge [int]$Matches[1] -and $Port -le [int]$Matches[2]) {
                        $portCovers = $true; break
                    }
                }
            }
            if (-not $portCovers) { return }

            # (4) 来源覆盖公网
            $af = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule -ErrorAction SilentlyContinue
            $remote = if ($af) { "$($af.RemoteAddress)" } else { '' }
            $remoteCoversPublic = ($remote -eq 'Any')
            if (-not $remoteCoversPublic -and $remote) {
                foreach ($part in ($remote -split ',')) {
                    $t = $part.Trim()
                    if (-not $t) { continue }
                    if ($t -match '^(\d{1,3})\.') {
                        $oct1 = [int]$Matches[1]
                        # 私网/保留段：10.x 172.16-31.x 192.168.x 127.x 169.254.x
                        $isPrivate = ($oct1 -eq 10) -or ($oct1 -eq 127) -or ($oct1 -eq 169) -or
                                     ($oct1 -eq 192 -and $t -match '^192\.168\.') -or
                                     ($oct1 -eq 172 -and $t -match '^172\.(1[6-9]|2\d|3[01])\.')
                        if (-not $isPrivate) { $remoteCoversPublic = $true; break }
                    }
                }
            }
            if (-not $remoteCoversPublic) { return }

            # (5) 程序作用域 —— 把"给 raserver 开的"和"给任意程序开的"分开。
            #     没有这一条就会把 43 条 Windows 自带规则误报成泄漏。
            $app = Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $rule -ErrorAction SilentlyContinue
            $svc = Get-NetFirewallServiceFilter -AssociatedNetFirewallRule $rule -ErrorAction SilentlyContinue
            $program = if ($app -and $app.Program) { "$($app.Program)" } else { '' }
            $service = if ($svc -and $svc.Service) { "$($svc.Service)" } else { '' }

            if ($program -or $service) {
                # 有作用域：只有作用域正好指向我们自己的 exe 才算暴露
                $isOurs = ($program -and $program -match [regex]::Escape($OwnExeName)) -or
                          ($service -and $service -match [regex]::Escape($OwnExeName))
                if (-not $isOurs) { return }
            }
            # 无作用域 → 对任意程序放行 → 真的是暴露

            [void]$found.Add([pscustomobject]@{
                Rule    = $rule.DisplayName
                Port    = $spec
                Remote  = $remote
                Program = $program
                Service = $service
            })
        }

    return @($found | Sort-Object -Property Rule -Unique)
}

# ---------------------------------------------------------------------
#  轻量检查：只找"明确写了 8637"的规则（快）。漏段式与 Any，那些交给深度检查。
# ---------------------------------------------------------------------
function Get-ExplicitPortRules([int]$Port) {
    return @(Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow -ErrorAction SilentlyContinue |
        Where-Object {
            $_.DisplayName -and
            ((Get-NetFirewallPortFilter -AssociatedNetFirewallRule $_ -ErrorAction SilentlyContinue).LocalPort -eq $Port)
        })
}

# ---------------------------------------------------------------------
#  展示某端口被哪些规则覆盖（只看端口写法与协议，不做五判定）
# ---------------------------------------------------------------------
function Show-PortStatus([int]$Port) {
    return @(Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow -ErrorAction SilentlyContinue |
        Where-Object {
            $pf = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $_ -ErrorAction SilentlyContinue
            if (-not $pf) { return $false }
            if ("$($pf.Protocol)".ToUpper() -ne 'TCP') { return $false }
            $spec = "$($pf.LocalPort)"
            if ($spec -eq 'Any') { return $true }
            foreach ($part in ($spec -split ',')) {
                $t = $part.Trim()
                if ($t -eq "$Port") { return $true }
                if ($t -match '^(\d+)-(\d+)$' -and $Port -ge [int]$Matches[1] -and $Port -le [int]$Matches[2]) { return $true }
            }
            return $false
        })
}

# =====================================================================
#  Show
# =====================================================================
if ($Action -eq 'Show') {
    Write-Host "=== TCP $SERVICE_PORT（服务端口）是否被放行 ===" -ForegroundColor Cyan
    $explicit = @(Get-ExplicitPortRules $SERVICE_PORT)
    if ($explicit.Count) {
        foreach ($r in $explicit) { Write-Host ("  [!!] 明确放行: {0}" -f $r.DisplayName) -ForegroundColor Red }
    } else {
        Write-Host '  无"明确写了 8637"的规则。' -ForegroundColor Green
    }

    if ($NoDeepScan) {
        Write-Host '  （-NoDeepScan：跳过深度检查，段式/Any 端口且无作用域的情形未覆盖）' -ForegroundColor Yellow
    } else {
        Write-Host ''
        Write-Host '  深度检查中（逐规则关联较慢，约 1-2 分钟）...' -ForegroundColor Yellow
        $exposed = @(Find-PublicExposureOfPort $SERVICE_PORT $SERVICE_EXE)
        if ($exposed.Count) {
            Write-Host ("  [!!] 发现 {0} 条会把 {1} 暴露给公网的规则：" -f $exposed.Count, $SERVICE_PORT) -ForegroundColor Red
            foreach ($r in $exposed) {
                Write-Host ("       · {0}  port={1} remote={2}" -f $r.Rule, $r.Port, $r.Remote) -ForegroundColor Red
                if ($r.Program) { Write-Host ("         程序作用域: {0}" -f $r.Program) }
                if ($r.Service) { Write-Host ("         服务作用域: {0}" -f $r.Service) }
            }
            Write-Host '  这些不是本脚本建的。请逐条确认来源后删除，例如：' -ForegroundColor Yellow
            Write-Host '    Remove-NetFirewallRule -DisplayName "<上面的名字>"' -ForegroundColor Yellow
        } else {
            Write-Host ("  深度检查通过：没有规则会把 TCP {0} 暴露给公网。" -f $SERVICE_PORT) -ForegroundColor Green
            Write-Host '  （已排除：非 TCP、端口不含 8637、来源不含公网、带程序作用域的规则）' -ForegroundColor DarkGray
        }
    }

    Write-Host ''
    Write-Host '=== 80 / 443 / 22 放行情况 ===' -ForegroundColor Cyan
    foreach ($p in 80, 443, 22) {
        $rs = @(Show-PortStatus $p)
        if ($rs.Count) {
            Write-Host ("  端口 {0,-4} : {1} 条规则覆盖" -f $p, $rs.Count) -ForegroundColor Green
            foreach ($r in ($rs | Select-Object -First 5)) { Write-Host ("      · {0}" -f $r.DisplayName) }
        } else {
            $c = if ($p -eq 22) { 'DarkGray' } else { 'Yellow' }
            Write-Host ("  端口 {0,-4} : 无（外部访问不到）" -f $p) -ForegroundColor $c
        }
    }
    return
}

# =====================================================================
#  权限
# =====================================================================
if (-not (Test-Admin)) {
    throw '需要管理员权限。请用「以管理员身份运行 PowerShell」再执行本脚本。'
}

# =====================================================================
#  Remove
# =====================================================================
if ($Action -eq 'Remove') {
    if (-not $PSCmdlet.ShouldProcess("$ServiceName 防火墙规则", '删除')) { return }
    foreach ($n in "$ServiceName-HTTP80", "$ServiceName-HTTPS443", "$ServiceName-SSH22") {
        $r = Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue
        if ($r) {
            Remove-NetFirewallRule -DisplayName $n
            Write-Host "  已删除 $n" -ForegroundColor Green
        } else {
            Write-Host "  $n 不存在，跳过"
        }
    }
    Write-Host ''
    Write-Host '（未动 8637 相关规则——那些不是本脚本建的。若要清理请先 -Action Show 看清再手动处理）'
    return
}

# =====================================================================
#  Apply
# =====================================================================
if (-not $PSCmdlet.ShouldProcess('Windows 防火墙入站规则', ('创建 80/443' + $(if ($OpenSSH) { ' + 22' } else { '' })))) { return }

$rules = @(
    @{ Name = "$ServiceName-HTTP80";   Port = 80;  Desc = 'Caddy HTTP（跳转 HTTPS + ACME HTTP-01 验证）' }
    @{ Name = "$ServiceName-HTTPS443"; Port = 443; Desc = 'Caddy HTTPS（唯一对外服务入口）' }
)
if ($OpenSSH) {
    $rules += @{ Name = "$ServiceName-SSH22"; Port = 22; Desc = 'SSH 远程管理（按需开启）' }
}

foreach ($r in $rules) {
    if (Get-NetFirewallRule -DisplayName $r.Name -ErrorAction SilentlyContinue) {
        Write-Host "  $($r.Name) 已存在，跳过创建"
        continue
    }
    New-NetFirewallRule -DisplayName $r.Name `
        -Description "$($r.Desc) —— $ServiceName 部署" `
        -Direction Inbound -Protocol TCP -LocalPort $r.Port `
        -Action Allow -Profile Any `
        -Group $ServiceName | Out-Null
    Write-Host ("  已创建 {0} (TCP {1}) —— {2}" -f $r.Name, $r.Port, $r.Desc) -ForegroundColor Green
}

# ---------------------------------------------------------------- 深度检查
if ($NoDeepScan) {
    Write-Host ''
    Write-Host '  -NoDeepScan：跳过 8637 暴露检查。' -ForegroundColor Yellow
} else {
    Write-Host ''
    Write-Host "=== 深度检查：是否有规则会把 TCP $SERVICE_PORT 暴露给公网 ===" -ForegroundColor Cyan
    Write-Host '  （约 1-2 分钟；五条判定条件见脚本头说明）' -ForegroundColor DarkGray
    $exposed = @(Find-PublicExposureOfPort $SERVICE_PORT $SERVICE_EXE)
    if ($exposed.Count) {
        Write-Host ("  [!!] 发现 {0} 条：" -f $exposed.Count) -ForegroundColor Red
        foreach ($r in $exposed) {
            Write-Host ("       · {0}  port={1} remote={2}" -f $r.Rule, $r.Port, $r.Remote) -ForegroundColor Red
        }
        Write-Host '  这些规则不是本脚本建的（本脚本从不创建 8637 规则）。' -ForegroundColor Yellow
        Write-Host '  请逐条确认来源；确认无用后删除：' -ForegroundColor Yellow
        Write-Host '    Remove-NetFirewallRule -DisplayName "<名字>"' -ForegroundColor Yellow
    } else {
        Write-Host ("  通过：没有规则会把 TCP {0} 暴露给公网。" -f $SERVICE_PORT) -ForegroundColor Green
    }
}

Write-Host ''
Write-Host '=== 完成 ===' -ForegroundColor Cyan
Write-Host '  复查：.\firewall-rules.ps1 -Action Show'
Write-Host '  撤销：.\firewall-rules.ps1 -Action Remove'
