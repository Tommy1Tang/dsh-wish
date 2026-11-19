#!/usr/bin/env pwsh
# 把 dsh-wish 推到 GitHub。
#
# 用法（在项目根目录）：
#   pwsh tools/push-to-github.ps1 -Owner 你的用户名 -Repo dsh-wish
#   pwsh tools/push-to-github.ps1 -Owner 你的用户名 -Repo dsh-wish -Proxy http://127.0.0.1:7897
#   pwsh tools/push-to-github.ps1 -Owner 你的用户名 -Repo dsh-wish -Create   # 需已登录 gh CLI
#
# 它做三件事：检查连通性 -> 配 remote -> push。不替你创建仓库（除非 -Create 且有 gh）。

param(
  [Parameter(Mandatory = $true)][string]$Repo,
  [Parameter(Mandatory = $true)][string]$Owner,
  [ValidateSet("public", "private")][string]$Visibility = "public",
  [string]$Proxy = "",
  [switch]$Create
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Stop-With($msg) {
  Write-Host "[x] $msg" -ForegroundColor Red
  exit 1
}
function Say-Ok($msg) {
  Write-Host "[ok] $msg" -ForegroundColor Green
}

# --- 1. 工作区必须干净 ----------------------------------------------------
$dirty = git status --porcelain
if ($dirty) {
  Write-Host $dirty
  Stop-With "工作区有未提交改动，先 git add + commit 再推"
}
Say-Ok "工作区干净"

# --- 2. 连通性 ------------------------------------------------------------
$proxyArgs = @()
if ($Proxy) {
  $proxyArgs = @("-c", "http.proxy=$Proxy", "-c", "https.proxy=$Proxy")
  Write-Host "  使用代理: $Proxy"
}

$reachable = $false
try {
  git @proxyArgs ls-remote --heads https://github.com/octocat/Hello-World.git 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { $reachable = $true }
} catch {
  $reachable = $false
}

if (-not $reachable) {
  Write-Host "  如果你有代理，加 -Proxy http://127.0.0.1:7897 重试" -ForegroundColor Yellow
  Write-Host "  或先自查: Test-NetConnection github.com -Port 443" -ForegroundColor Yellow
  Stop-With "连不上 github.com:443"
}
Say-Ok "能连上 github.com"

# --- 3. 可选：用 gh 建仓库 ------------------------------------------------
$full = "$Owner/$Repo"
$gh = Get-Command gh -ErrorAction SilentlyContinue

if ($Create) {
  if (-not $gh) { Stop-With "-Create 需要 gh CLI，未安装" }
  $ghArgs = @("repo", "create", $Repo, "--source", ".", "--push", "--" + $Visibility)
  Write-Host "  gh repo create $Repo ..."
  & gh @ghArgs
  if ($LASTEXITCODE -ne 0) { Stop-With "gh repo create 失败" }
  Say-Ok "仓库已创建并推送"
  Write-Host ""
  Write-Host "仓库地址: https://github.com/$full" -ForegroundColor Cyan
  exit 0
}

# --- 4. 配 remote 并推 ----------------------------------------------------
$url = "https://github.com/$full.git"
$existing = $null
try { $existing = git remote get-url origin 2>$null } catch { $existing = $null }

if ($existing) {
  git remote set-url origin $url
  Say-Ok "origin 已改为 $url"
} else {
  git remote add origin $url
  Say-Ok "origin 已设为 $url"
}

Write-Host "  推送 main ..."
git @proxyArgs push -u origin main
if ($LASTEXITCODE -ne 0) {
  Write-Host "  常见原因：" -ForegroundColor Yellow
  Write-Host "    - 没有凭据：配 Git Credential Manager，或用 PAT" -ForegroundColor Yellow
  Write-Host "    - 仓库还没建：去 https://github.com/new 建空仓库 $Repo" -ForegroundColor Yellow
  Stop-With "推送失败"
}
Say-Ok "推送完成"
Write-Host ""
Write-Host "仓库地址: https://github.com/$full" -ForegroundColor Cyan
