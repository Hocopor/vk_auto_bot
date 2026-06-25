# Stop hook: blocks finishing the turn if project files changed after the last STATE.md update.
# PORTABLE: derives project root from the Stop-hook payload (cwd) or $env:CLAUDE_PROJECT_DIR.
# Copy this file + settings.json into any project unchanged - no paths to edit.
# ASCII only! PowerShell 5.1 reads a BOM-less .ps1 as ANSI and breaks on non-ASCII.
$inputJson = [Console]::In.ReadToEnd()
try { $payload = $inputJson | ConvertFrom-Json } catch { $payload = $null }
# loop guard: if we already blocked this Stop once, let it pass
if ($payload -and $payload.stop_hook_active) { exit 0 }

$root = $null
if ($payload -and $payload.cwd) { $root = $payload.cwd }
if (-not $root -and $env:CLAUDE_PROJECT_DIR) { $root = $env:CLAUDE_PROJECT_DIR }
if (-not $root) { exit 0 }

$state = Get-Item (Join-Path $root "STATE.md") -ErrorAction SilentlyContinue
if (-not $state) { exit 0 }

# folders that are noise (deps, build output, vcs, caches) - tune per project if needed
$exclude = '\\(\.claude|\.git|data|__pycache__|\.venv|venv|node_modules|dist|build|\.next|target|bin|obj)(\\|$)'
$newest = $null
$files = Get-ChildItem $root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch $exclude -and $_.Name -ne 'STATE.md' -and $_.Name -ne 'PLAN.md' }
foreach ($f in $files) {
    if ($null -eq $newest -or $f.LastWriteTime -gt $newest) { $newest = $f.LastWriteTime }
}

if ($newest -and $newest -gt $state.LastWriteTime) {
    $msg = "Project files changed after the last STATE.md update. Before finishing: (1) update STATE.md - current point, what was done and the result, next step; (2) tick completed checkboxes in PLAN.md; (3) add any new gotchas to STATE.md -> Nuances section."
    @{ decision = "block"; reason = $msg } | ConvertTo-Json -Compress
}
exit 0
