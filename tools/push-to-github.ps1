#!/usr/bin/env pwsh
# 把 dsh-wish 推到 GitHub（SSH）。
#
# 前置：仓库已存在（在 https://github.com/new 建一个空的，别勾 README/gitignore/license），
#       且本机 SSH key 已在 GitHub 上登记。
#
# 用法：
#   .\tools\push-to-github.ps1                      # 自动识别 GitHub 账号
#   .\tools\push-to-github.ps1 -Repo dsh-wish       # 指定仓库名（默认 dsh-wish）
#   .\tools\push-to-github.ps1 -Owner SomeoneElse   # 指定组织/账号
#   .\tools\push-to-github.ps1 -DryRun              # 只检查，不推

param(
  [string]$Repo = "dsh-wish",
  [string]$Owner = "",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Stop-With($msg) { Write-Host "[x] $msg" -ForegroundColor Red; exit 1 }
function Say-Ok($msg)    { Write-Host "[ok] $msg" -ForegroundColor Green }

# --- 1. 工作区干净 --------------------------------------------------------
$dirty = git status --porcelain
if ($dirty) {
  Write-Host $dirty
  Stop-With "工作区有未提交改动，先 git add + commit"
}
Say-Ok "工作区干净"

# --- 2. 识别账号（SSH 认证 + 从欢迎语里取用户名）--------------------------
# 注意：`ssh -T git@github.com` 把欢迎语写到 stderr，且认证成功也返回 exit 1。
# 在 $ErrorActionPreference='Stop' 下这会被当成致命错误 —— 所以这段要临时放宽。
$env:GIT_SSH_COMMAND = "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$authText = (& ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 -T git@github.com 2>&1 | Out-String)
$ErrorActionPreference = $prevEap

if ($authText -notmatch "successfully authenticated") {
  Write-Host $authText
  Stop-With "SSH 认证失败：确认 id_ed25519 已加到 GitHub 账号的 SSH keys"
}
Say-Ok "SSH 认证通过"

if (-not $Owner) {
  if ($authText -match "Hi ([A-Za-z0-9\-]+)!") {
    $Owner = $Matches[1]
  } else {
    Stop-With "没能从认证欢迎语里识别账号，请用 -Owner 指定"
  }
}
Say-Ok "账号: $Owner"

$full = "$Owner/$Repo"
$url  = "git@github.com:$full.git"

# --- 3. 仓库必须已存在 ----------------------------------------------------
$probe = git ls-remote --heads $url 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "  下一步：去 https://github.com/new 建一个空仓库，名字填 $Repo" -ForegroundColor Yellow
  Write-Host "  不要勾选 README / .gitignore / license（本仓库已经有了）" -ForegroundColor Yellow
  Stop-With "远程仓库 $full 还不存在"
}
Say-Ok "远程仓库存在"

# --- 4. 配 remote ---------------------------------------------------------
$existing = $null
try { $existing = git remote get-url origin 2>$null } catch { $existing = $null }
if ($existing -eq $url) {
  Say-Ok "origin 已是 $url"
} elseif ($existing) {
  git remote set-url origin $url
  Say-Ok "origin 改为 $url"
} else {
  git remote add origin $url
  Say-Ok "origin 设为 $url"
}

# --- 5. 推 ---------------------------------------------------------------
$branch = git branch --show-current
if (-not $branch) { Stop-With "当前不在任何分支上" }

if ($DryRun) {
  Say-Ok "[DryRun] 会执行: git push -u origin $branch"
  exit 0
}

Write-Host "  推送 $branch ..."
git push -u origin $branch
if ($LASTEXITCODE -ne 0) { Stop-With "推送失败（见上面的 git 输出）" }

Say-Ok "推送完成"
Write-Host ""
Write-Host "仓库地址: https://github.com/$full" -ForegroundColor Cyan
