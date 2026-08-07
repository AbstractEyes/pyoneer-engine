# Stop Dropbox syncing the regenerable parts of this repo.
#
#   powershell -ExecutionPolicy Bypass -File tools\dropbox_ignore.ps1
#
# WHY
# Dropbox syncs file-by-file with no understanding of a repo as a unit. When it
# catches a directory mid-write it does not merge, it forks the file into a
# "conflicted copy" -- this repo already has one, from a MacBook, dated
# 2025-12-05. Doing that to .git/index or a packfile corrupts the repository
# rather than politely renaming a spare.
#
# .gitignore does NOT help: it stops git tracking those paths, while Dropbox
# still faithfully syncs every byte. This sets Dropbox's own per-folder ignore
# attribute (an NTFS alternate data stream), which is a different mechanism.
#
# Re-run after recreating .venv, or when new __pycache__ directories appear.
# Ignored content stays on disk; it just stops being uploaded.
#
# .git is deliberately NOT included. Ignoring it removes the corruption risk
# but also removes Dropbox as the backup of your history -- correct only once
# a git remote exists. Pass -IncludeGit once you have pushed.

param([switch]$IncludeGit, [switch]$Undo)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$targets = @()
foreach ($d in @('.venv', '.idea')) {
    if (Test-Path $d) { $targets += (Resolve-Path $d).Path }
}
$targets += Get-ChildItem -Path $repo -Filter '__pycache__' -Directory -Recurse -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notlike '*\.venv\*' } |
            ForEach-Object { $_.FullName }
if ($IncludeGit -and (Test-Path '.git')) { $targets += (Resolve-Path '.git').Path }

$changed = 0
foreach ($t in $targets) {
    try {
        if ($Undo) {
            Remove-Item -Path $t -Stream com.dropbox.ignored -ErrorAction SilentlyContinue
        } else {
            Set-Content -Path $t -Stream com.dropbox.ignored -Value 1 -ErrorAction Stop
        }
        $changed++
    } catch {
        Write-Output "FAILED $t : $($_.Exception.Message)"
    }
}

$verb = if ($Undo) { 'un-ignored' } else { 'ignored' }
Write-Output "$verb $changed path(s)"
if (-not $IncludeGit -and -not $Undo) {
    Write-Output ".git left syncing - re-run with -IncludeGit once you have a git remote"
}
