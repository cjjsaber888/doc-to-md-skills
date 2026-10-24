# run_pipeline.ps1 — 长批作业收尾链执行器模板
#
# 适配新项目：改下面 $work / $py 两行，以及「链步骤」区的脚本名清单。
# 由 ocr_watchdog.ps1（计划任务每 2 分钟探针）拉起，也可手动执行。
#
# 守卫：
#   ① 忙检查：主批作业（如 OCR 调度器）在跑则不插队
#   ② 文件锁原子抢占（New-Item 同路径只有一个调用方能建成，防双链）
#   ③ 每步骤失败自动重试 3 次；链级尝试 6 次上限，超过写 FAIL 标记转人工
# 全链可反复重入：OCR 按 state 断点、向量化按 chunk ID 增量、结构化幂等重建。
$ErrorActionPreference = 'Continue'
$work  = '<WORKSPACE>'   # ← 改这里：项目工作目录
$py    = 'C:/Users/<USER>\.workbuddy\binaries\python\envs\ocr\Scripts\python.exe'  # ← 改这里：受管 venv python
$lock  = Join-Path $work 'pipeline.lock'
$done  = Join-Path $work 'pipeline_done.marker'
$fail  = Join-Path $work 'pipeline_fail.marker'
$att   = Join-Path $work 'pipeline_attempts.txt'
$logf  = Join-Path $work 'pipeline_log.txt'
$so    = Join-Path $work '_step_out.txt'
$se    = Join-Path $work '_step_err.txt'

function L($m) { "$(Get-Date -Format 'MM-dd HH:mm:ss') $m" | Out-File -FilePath $logf -Append -Encoding utf8 }

if (Test-Path $done) { exit 0 }
if (Test-Path $fail) { L 'chain: FAIL 标记存在，停止'; exit 1 }

# 守卫①：主批作业若在跑（bash 守护环或本链之外的实例），不插队
$busy = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*ocr_full.py*' }
if ($busy) { L 'chain: OCR 调度器正在运行，本轮不启动'; exit 0 }

# 守卫②：文件锁原子抢占
$gotLock = $null
try { $gotLock = New-Item -Path $lock -ItemType File -ErrorAction SilentlyContinue } catch {}
if (-not $gotLock) {
    $age = (New-TimeSpan -Start (Get-Item $lock).LastWriteTime -End (Get-Date)).TotalMinutes
    if ($age -gt 360) {
        L "chain: 锁过期 $([int]$age) 分钟，强制接管"
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
        try { $gotLock = New-Item -Path $lock -ItemType File -ErrorAction SilentlyContinue } catch {}
    }
    if (-not $gotLock) { L 'chain: 锁被其他链占用，退出'; exit 0 }
}

$n = 0
if (Test-Path $att) { try { $n = [int](Get-Content $att -ErrorAction SilentlyContinue) } catch {} }
$n++
Set-Content -Path $att -Value $n
if ($n -gt 6) {
    'too many attempts' | Out-File $fail -Encoding utf8
    L 'chain: 重试超过 6 次，写 FAIL 标记，等人工'
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
    exit 1
}
Set-Content -Path $lock -Value "pid=$PID start=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
L "chain: 启动（第 $n 次尝试）"

function Run-Step($name, $script) {
    for ($i = 1; $i -le 3; $i++) {
        L "chain: 步骤[$name] 第 $i/3 次启动"
        $p = Start-Process -FilePath $py -ArgumentList $script -WorkingDirectory $work `
             -Wait -PassThru -WindowStyle Hidden `
             -RedirectStandardOutput $so -RedirectStandardError $se
        $tail = ''
        if (Test-Path $se) { $tail = ((Get-Content $se -Tail 3 -ErrorAction SilentlyContinue) -join ' / ') }
        L "chain: 步骤[$name] rc=$($p.ExitCode) err=$tail"
        if ($p.ExitCode -eq 0) { return $true }
        Start-Sleep -Seconds 15
    }
    L "chain: 步骤[$name] 三次均失败"
    return $false
}

# === 链步骤（按项目实际改这一区）===
$ok = $true
if     (-not (Run-Step 'OCR续跑'      'ocr_full.py'))      { $ok = $false }
if     ($ok -and -not (Run-Step 'frontmatter校准' 'post_ocr_fix.py')) { $ok = $false }
if     ($ok -and -not (Run-Step '结构化重建'     'structure.py'))     { $ok = $false }
if     ($ok -and -not (Run-Step '向量化增量'     'embed.py'))         { $ok = $false }
if     ($ok -and -not (Run-Step '终校准'         'final_calibrate.py')) { $ok = $false }

if ($ok) {
    "done $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File $done -Encoding utf8
    L 'chain: 全链完成，写 DONE 标记'
} else {
    L 'chain: 有步骤失败，不写 DONE，等守护下一轮重试'
}
Remove-Item $lock -Force -ErrorAction SilentlyContinue
