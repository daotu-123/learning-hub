<#
.SYNOPSIS
    从 backup-data.ps1 产出的压缩包恢复 LearningHub 数据目录。

.DESCRIPTION
    先校验 manifest 里的 SHA256，再解包落地。**校验不过就拒绝恢复**——
    备份做完不等于备份可用，这一点必须由恢复侧兜底。

    安全约定（承重，别改）：
      目标目录非空时必须显式加 -Force，否则直接拒绝。
      理由：数据目录里是账号、会话、usage.db、壁纸。一次"顺手恢复到旧目录"
      会把当前的账号和统计覆盖成上个月的，而这种覆盖没有撤销按钮。
      本脚本刻意不提供"智能合并"——合并语义（哪个文件算新？冲突怎么办？）
      在没有明确规则的情况下只会制造更难排查的问题。

    流程：
      1) 解压到临时目录
      2) 读 .manifest.txt，逐条比对 SHA256 与字节数
      3) 校验全过才落地；任何一条不符 → 整体放弃，目标目录一个字节都不动
      4) 打印恢复出的文件清单（路径 + 大小），供人眼确认

    恢复后必须做的事：服务以该数据目录重启，且**所有已登录设备要重新登录**
    （sessions.json 被替换成旧版本，里面的会话令牌与新服务端状态不匹配）。

.PARAMETER BackupFile
    backup-data.ps1 产出的 .zip。必填。

.PARAMETER DataDir
    目标数据目录。必填。

.PARAMETER Force
    允许覆盖非空的目标目录。不给且目录非空 → 拒绝执行。

.PARAMETER SkipVerify
    跳过 SHA256 校验。**不建议**；仅在 manifest 丢失但仍要抢救数据时用，
    且脚本会明确告警。

.EXAMPLE
    .\restore-data.ps1 -BackupFile E:\LH-backups\LearningHub-data-20261021-020000.zip -DataDir D:\LearningHub\data-restore
    .\restore-data.ps1 -BackupFile <zip> -DataDir D:\LearningHub\data -Force
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [switch]$Force,
    [switch]$SkipVerify
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $BackupFile)) {
    throw "备份文件不存在：$BackupFile"
}
$BackupFile = (Resolve-Path $BackupFile).Path
$DataDir = [System.IO.Path]::GetFullPath($DataDir)

$manifestPath = "$BackupFile.manifest.txt"

Write-Host '=== 恢复前检查 ===' -ForegroundColor Cyan
Write-Host ("  备份文件 : {0}" -f $BackupFile)
Write-Host ("  目标目录 : {0}" -f $DataDir)

# ---- 目标目录非空必须显式确认 ---------------------------------------
if (Test-Path $DataDir) {
    $existing = @(Get-ChildItem -Path $DataDir -Recurse -File -Force -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        if (-not $Force) {
            Write-Host ''
            Write-Host ("拒绝执行：目标目录非空（{0} 个文件）。" -f $existing.Count) -ForegroundColor Red
            Write-Host '  覆盖数据目录会替换掉账号、会话、usage.db 与壁纸，且没有撤销按钮。'
            Write-Host '  确认要覆盖请显式加 -Force；若想先看看内容，恢复到另一个空目录。'
            exit 1
        }
        Write-Host ("  目标目录已有 {0} 个文件，-Force 已指定，将覆盖。" -f $existing.Count) -ForegroundColor Yellow
        Write-Host '  建议先手工备份一次：Copy-Item -Recurse $DataDir $DataDir.bak' -ForegroundColor Yellow
    }
}

if (-not (Test-Path $manifestPath)) {
    if ($SkipVerify) {
        Write-Warning 'manifest 不存在，已按 -SkipVerify 跳过校验。数据完整性未经确认。'
    } else {
        Write-Host ''
        Write-Host "拒绝执行：找不到清单文件 $manifestPath" -ForegroundColor Red
        Write-Host '  没有清单就无法校验备份是否完好。确认仍要恢复请加 -SkipVerify（不推荐）。'
        exit 1
    }
}

if (-not $PSCmdlet.ShouldProcess($DataDir, '从备份恢复')) { return }

# ---- 1) 解压到临时目录 ----------------------------------------------
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("lh-restore-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
try {
    Write-Host ''
    Write-Host '=== 解压 ===' -ForegroundColor Cyan
    # 用 ZipFile.ExtractToDirectory 而不是 Expand-Archive：后者在无控制台
    # 环境下照样把进度条写进输出流（与 backup-data.ps1 里同一个坑）。
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    [System.IO.Compression.ZipFile]::ExtractToDirectory($BackupFile, $stage)
    $staged = @(Get-ChildItem -Path $stage -Recurse -File -Force)
    Write-Host ("  解出 {0} 个文件" -f $staged.Count)

    # ---- 2) 校验 ----------------------------------------------------
    if (-not $SkipVerify) {
        Write-Host ''
        Write-Host '=== 校验 SHA256 ===' -ForegroundColor Cyan
        $lines = Get-Content -Path $manifestPath -Encoding UTF8 | Where-Object { $_ -and -not $_.StartsWith('#') }
        $bad = New-Object System.Collections.ArrayList
        $checked = 0
        foreach ($line in $lines) {
            if ($line -notmatch '^([0-9a-fA-F]{64})\s+(\d+)\s+(.+)$') { continue }
            $wantHash = $Matches[1].ToLower()
            $wantSize = [int64]$Matches[2]
            $rel = $Matches[3].Trim()
            $p = Join-Path $stage $rel
            if (-not (Test-Path $p)) {
                [void]$bad.Add("缺失: $rel")
                continue
            }
            $actual = Get-Item $p
            if ($actual.Length -ne $wantSize) {
                [void]$bad.Add("大小不符: $rel  期望 $wantSize  实际 $($actual.Length)")
                continue
            }
            $actualHash = (Get-FileHash -Path $p -Algorithm SHA256).Hash.ToLower()
            if ($actualHash -ne $wantHash) {
                [void]$bad.Add("哈希不符: $rel")
                continue
            }
            $checked++
        }
        Write-Host ("  已校验 {0} 个文件，不一致 {1} 个" -f $checked, $bad.Count)
        if ($bad.Count) {
            Write-Host ''
            Write-Host '拒绝恢复：备份内容与清单不一致。' -ForegroundColor Red
            $bad | Select-Object -First 10 | ForEach-Object { Write-Host ("    [!!] {0}" -f $_) }
            Write-Host '  目标目录未做任何改动。'
            Write-Host '  这通常意味着备份文件损坏或被截断——换一个备份重试，'
            Write-Host '  并检查存放备份的磁盘/同步目录。'
            exit 1
        }
        Write-Host '  全部一致。' -ForegroundColor Green
    }

    # ---- 3) 落地 ----------------------------------------------------
    Write-Host ''
    Write-Host '=== 落地 ===' -ForegroundColor Cyan
    if (-not (Test-Path $DataDir)) {
        New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
    }
    $restored = 0
    foreach ($f in ($staged | Sort-Object FullName)) {
        $rel = $f.FullName.Substring($stage.Length).TrimStart('\')
        $dest = Join-Path $DataDir $rel
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
        Copy-Item -Path $f.FullName -Destination $dest -Force
        $restored++
    }
    Write-Host ("  已恢复 {0} 个文件到 {1}" -f $restored, $DataDir) -ForegroundColor Green

    # ---- 4) 清单 ----------------------------------------------------
    Write-Host ''
    Write-Host '=== 恢复内容 ===' -ForegroundColor Cyan
    $staged | Sort-Object FullName | ForEach-Object {
        $rel = $_.FullName.Substring($stage.Length).TrimStart('\')
        Write-Host ("  {0,-52} {1,12:N0} B" -f $rel, $_.Length)
    }
}
finally {
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue }
}

Write-Host ''
Write-Host '=== 恢复后必做 ===' -ForegroundColor Cyan
Write-Host '  1) 以该数据目录重启服务（Restart-Service LearningHub）'
Write-Host '  2) 所有已登录设备需重新登录：sessions.json 来自旧备份，'
Write-Host '     里面的会话令牌与服务端当前状态不匹配。'
Write-Host '  3) 核对一次 /api/summary 与 /api/photos 是否正常。'
