<#
.SYNOPSIS
    每日备份 LearningHub 数据目录（server/data）。

.DESCRIPTION
    产出 `<BackupRoot>\LearningHub-data-YYYYMMDD-HHMMSS.zip` + 同名 `.manifest.txt`，
    并按 -RetentionDays 清理旧包（默认 30 天）。

    备份内容：数据目录下**除日志类之外的全部文件**。
    明确包含 owner 点名的几项：settings.json、usage.db、account.json、
    sessions.json、media_url_secret、wallpapers\。
    之所以不按那份清单逐项列，而是"整目录减排除项"：清单漏一个文件
    就等于那个文件永远恢复不回来，而"恢复时发现少东西"是最难发现的故障。
    整目录减排除项是超集，漏不了。

    排除项及理由：
      backups\    本脚本自己的输出目录，收进来会递归膨胀
      logs\       服务 tee 出来的 service-std{out,err}.log，诊断用、会重建
      *.log       uvicorn 的 server.log（含轮转 .1/.2），诊断用
      openmaic_logs\  AI 课堂的任务日志，体积大且可重建
      .health_probe  健康探针的临时文件（正常情况下不该存在）

    manifest.txt 里记录每个文件的相对路径、字节数、SHA256。
    恢复脚本会拿它逐条校验——备份做完不等于备份可用，校验过才算。

    保留期按**文件名里的时间戳**判断，不按文件 mtime：zip 被拷贝/同步过
    之后 mtime 会变，按 mtime 清理可能误删唯一的新备份。

    建议用任务计划程序每日执行（见 docs/deploy-windows.md）。

.PARAMETER DataDir
    数据目录（对应 HUB_DATA_DIR）。必填。

.PARAMETER BackupRoot
    备份存放根目录。默认 <DataDir>\..\backups，即与数据目录同级。

.PARAMETER RetentionDays
    保留天数。默认 30。

.PARAMETER WhatIf
    只打印将备份/将删除的内容，不动磁盘。

.EXAMPLE
    .\backup-data.ps1 -DataDir D:\LearningHub\data
    .\backup-data.ps1 -DataDir D:\LearningHub\data -BackupRoot E:\LH-backups -RetentionDays 30
    .\backup-data.ps1 -DataDir D:\LearningHub\data -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$BackupRoot,
    [int]$RetentionDays = 30
    # 不显式声明 -WhatIf：SupportsShouldProcess 已经自动提供它，
    # 再写一个 [switch]$WhatIf 会报「对命令多次定义了名为 WhatIf 的参数」。
    # 自动那个同样会置 $WhatIf 变量，下面的判断照样成立。
)

$ErrorActionPreference = 'Stop'

# Compress-Archive 默认写进度条。脚本被任务计划程序调用、stdout 重定向到
# 文件时，那一大片 "正在创建存档文件… [oooo]" 会把日志冲爆，而且每条都带
# 回车覆盖，事后根本无法阅读。静默掉。
$ProgressPreference = 'SilentlyContinue'

if (-not (Test-Path $DataDir)) {
    throw "数据目录不存在：$DataDir"
}
$DataDir = (Resolve-Path $DataDir).Path

if (-not $BackupRoot) {
    # 默认与数据目录同级：D:\LearningHub\data → D:\LearningHub\backups
    $parent = Split-Path -Parent $DataDir
    $BackupRoot = Join-Path $parent 'backups'
}

# 排除规则。用相对路径匹配，且只匹配目录名/文件名，避免误伤业务文件。
$excludeDirs = @('backups', 'logs', 'openmaic_logs')
$excludeFiles = @('*.log', '.health_probe')

function Get-IncludedFiles([string]$Root) {
    $items = Get-ChildItem -Path $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $rel = $_.FullName.Substring($Root.Length).TrimStart('\', '/')
            $first = ($rel -split '[\\/]')[0]
            if ($excludeDirs -contains $first) { return $false }
            foreach ($pat in $excludeFiles) {
                if ($_.Name -like $pat) { return $false }
            }
            return $true
        }
    return @($items)
}

function Format-Size([double]$Bytes) {
    # 数据目录通常是几 MB 到几十 MB，但全新部署只有几 KB。
    # 一律按 MB 显示会把 6 KB 印成 "0.0 MB"，看着像没备份成功。
    if ($Bytes -ge 1GB) { return ("{0:N2} GB" -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ("{0:N1} MB" -f ($Bytes / 1MB)) }
    return ("{0:N0} KB" -f ($Bytes / 1KB))
}

$files = Get-IncludedFiles $DataDir
if (-not $files.Count) {
    Write-Warning "数据目录下没有可备份的文件：$DataDir"
    return
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$zipName = "LearningHub-data-$stamp.zip"
$zipPath = Join-Path $BackupRoot $zipName
$manifestPath = "$zipPath.manifest.txt"

$totalBytes = ($files | Measure-Object -Property Length -Sum).Sum
Write-Host "=== 备份 ===" -ForegroundColor Cyan
Write-Host ("  源目录   : {0}" -f $DataDir)
Write-Host ("  目标     : {0}" -f $zipPath)
Write-Host ("  文件数   : {0}" -f $files.Count)
Write-Host ("  总大小   : {0}" -f (Format-Size $totalBytes))
Write-Host ("  保留期   : {0} 天" -f $RetentionDays)

if ($WhatIf) {
    Write-Host "`n  [WhatIf] 将备份以下文件："
    $files | Sort-Object FullName | ForEach-Object {
        $rel = $_.FullName.Substring($DataDir.Length).TrimStart('\')
        Write-Host ("    {0,-52} {1,10:N0} B" -f $rel, $_.Length)
    }
    return
}

if (-not $PSCmdlet.ShouldProcess($zipPath, '创建备份压缩包')) { return }

New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

# ---- 打包到临时目录再压，避免把排除项也打进去 -----------------------
$stage = Join-Path $BackupRoot ".stage-$stamp"
New-Item -ItemType Directory -Path $stage -Force | Out-Null
try {
    $manifest = New-Object System.Collections.ArrayList
    [void]$manifest.Add("# LearningHub 数据备份清单")
    [void]$manifest.Add("# 生成时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')")
    [void]$manifest.Add("# 源目录  : $DataDir")
    [void]$manifest.Add("# 格式    : <sha256>  <bytes>  <相对路径>")
    [void]$manifest.Add("")

    $idx = 0
    foreach ($f in ($files | Sort-Object FullName)) {
        $idx++
        $rel = $f.FullName.Substring($DataDir.Length).TrimStart('\')
        $dest = Join-Path $stage $rel
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
        Copy-Item -Path $f.FullName -Destination $dest -Force

        $hash = (Get-FileHash -Path $f.FullName -Algorithm SHA256).Hash
        [void]$manifest.Add(("{0}  {1,12}  {2}" -f $hash, $f.Length, $rel))

        if ($idx % 20 -eq 0 -or $idx -eq $files.Count) {
            Write-Host ("  已处理 {0}/{1}" -f $idx, $files.Count)
        }
    }

    # 压缩。用 .NET 的 ZipFile 而不是 Compress-Archive：
    #   1) Compress-Archive 在无控制台环境（任务计划程序 / 重定向到文件）下
    #      仍会把进度条写进输出流，把日志冲爆且带回车覆盖，事后无法阅读；
    #   2) ZipFile.CreateFromDirectory 明显更快（本机 6 文件实测快一倍以上）；
    #   3) 两者都是内置的，不引入新依赖。
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stage, $zipPath, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    [System.IO.File]::WriteAllText($manifestPath, ($manifest -join "`r`n") + "`r`n", [System.Text.UTF8Encoding]::new($true))
}
finally {
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue }
}

$zipSize = (Get-Item $zipPath).Length
Write-Host ("  完成     : {0} ({1})" -f $zipName, (Format-Size $zipSize)) -ForegroundColor Green
Write-Host ("  清单     : {0}" -f (Split-Path -Leaf $manifestPath)) -ForegroundColor Green

# ---- 清理旧备份 ------------------------------------------------------
$cutoff = (Get-Date).AddDays(-$RetentionDays)
$pruned = 0
Get-ChildItem -Path $BackupRoot -Filter 'LearningHub-data-*.zip' -File -ErrorAction SilentlyContinue |
    ForEach-Object {
        # 从文件名解析时间戳；解析不了的保留（宁可多留一个也不要误删）
        if ($_.Name -match 'LearningHub-data-(\d{8})-(\d{6})\.zip$') {
            $ts = [datetime]::ParseExact("$($Matches[1])$($Matches[2])", 'yyyyMMddHHmmss', $null)
            if ($ts -lt $cutoff) {
                Remove-Item $_.FullName -Force
                $sidecar = "$($_.FullName).manifest.txt"
                if (Test-Path $sidecar) { Remove-Item $sidecar -Force }
                $pruned++
            }
        }
    }
if ($pruned) { Write-Host ("  已清理   : {0} 个超过 {1} 天的旧备份" -f $pruned, $RetentionDays) }

# ---- 日志 ------------------------------------------------------------
$logLine = "{0}  {1}  {2} files  {3}  pruned={4}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $zipName, $files.Count, (Format-Size $zipSize), $pruned
Add-Content -Path (Join-Path $BackupRoot 'backup.log') -Value $logLine -Encoding UTF8

Write-Host ''
Write-Host '=== 恢复方法 ===' -ForegroundColor Cyan
Write-Host ("  .\restore-data.ps1 -BackupFile '{0}' -DataDir <目标目录>" -f $zipPath)
Write-Host '  （目标目录非空时必须显式加 -Force，脚本不会静默覆盖）'
