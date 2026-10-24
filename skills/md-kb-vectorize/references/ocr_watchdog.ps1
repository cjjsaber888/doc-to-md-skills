# ocr_watchdog.ps1 — 长批作业计划任务探针模板（每 2 分钟触发一次）
#
# 适配新项目只需改下面 $work 一行。
# 注册：schtasks /create /tn "<项目名>_Watchdog" /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File <本脚本绝对路径>" /sc minute /mo 2 /f
#
# 由来（2026-10-23 外环西段实测）：run_in_background 的 bash 守护环生命周期绑定会话，
# 会话一断全链殉葬（白停 33 小时）。本探针用 Windows 计划任务承载，与会话彻底解耦。
#
# 职责：
#   ① 保活：无链在跑且无 DONE 标记 → 拉起 run_pipeline.ps1
#   ② 停滞检测：ocr_full.py 在跑但日志 30 分钟无更新 → 杀进程让下一轮重启
#      （只杀命令行带本项目特有标记的子进程，避免误伤其他项目在跑的 OCR）
#   ③ 心跳：每次触发刷新 watchdog_heartbeat.txt，供人工确认探针活着
$work   = '<WORKSPACE>'   # ← 改这里：项目工作目录
$logf   = Join-Path $work 'watchdog_log.txt'
$hb     = Join-Path $work 'watchdog_heartbeat.txt'
$lock   = Join-Path $work 'pipeline.lock'
$done   = Join-Path $work 'pipeline_done.marker'
$failm  = Join-Path $work 'pipeline_fail.marker'
$ocrlog = Join-Path $work 'ocr_full_log.txt'
$chain  = Join-Path $work 'run_pipeline.ps1'

Get-Date -Format 'yyyy-MM-dd HH:mm:ss' | Out-File $hb -Encoding utf8

function L($m) { "$(Get-Date -Format 'MM-dd HH:mm:ss') $m" | Out-File -FilePath $logf -Append -Encoding utf8 }

if (Test-Path $done) { exit 0 }
if (Test-Path $failm) { L 'watchdog: FAIL 标记存在，停止干预，等人工'; exit 0 }

$procs = Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='python.exe' OR Name='cmd.exe'" |
    Where-Object { $_.CommandLine -like '*run_pipeline*' -or $_.CommandLine -like '*ocr_full.py*' }

# 停滞检测：只针对 ocr_full.py 进程（链的其他步骤不写 ocr_full_log，不能误杀）
$ocr = $procs | Where-Object { $_.CommandLine -like '*ocr_full.py*' }
if ($ocr -and (Test-Path $ocrlog)) {
    $stall = (New-TimeSpan -Start (Get-Item $ocrlog).LastWriteTime -End (Get-Date)).TotalMinutes
    if ($stall -gt 30) {
        L "watchdog: OCR 进程存活但日志停滞 $([int]$stall) 分钟，杀进程等重启"
        # 只杀本项目的引擎子进程（按 _ocr_full_chunk 标记识别，避免误伤其他项目 OCR）
        $kids = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -like '*_ocr_full_chunk*' }
        $ocr | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        $kids | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 3
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
        $procs = $null
    }
}

if ($procs) { exit 0 }

if (Test-Path $lock) {
    $age = (New-TimeSpan -Start (Get-Item $lock).LastWriteTime -End (Get-Date)).TotalMinutes
    if ($age -lt 360) { exit 0 }
    L "watchdog: 锁过期 $([int]$age) 分钟，清除"
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}

L 'watchdog: 未检测到运行中的流水线，拉起收尾链'
Start-Process -FilePath 'powershell.exe' `
    -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',$chain `
    -WindowStyle Hidden
L 'watchdog: 收尾链已拉起（run_pipeline.ps1）'
