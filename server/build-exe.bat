@echo off
REM ===================================================================
REM  LearningHub Windows build script (M3-P1-1, VERSION added in P1-7)
REM
REM  Usage: run from anywhere - "build-exe.bat"
REM
REM  Output (three exes, identical code, different Windows subsystem):
REM    ..\exe\GUI app .exe         GUI     - desktop double-click, no console window
REM    ..\exe\LearningHubSvc.exe  CONSOLE - for the service, stdout/stderr have somewhere to go
REM    ..\exe\LearningHubManage.exe CONSOLE - manage CLI (set-password)
REM  Plus ..\exe\VERSION - see "Why VERSION" below.
REM
REM  Why this script instead of calling PyInstaller directly:
REM    A distpath written in the .spec file has NO effect (PyInstaller 6 does not
REM    read that variable; it only injects a read-only DISTPATH). The output
REM    directory can only be set via --distpath. The old README relied on a manual
REM    "copy" step to move the artifact into exe\; when that step was skipped,
REM    exe\ kept a stale build while the build log still showed success. This
REM    build found exactly that: the artifact in exe\ was from 10-18, two
REM    milestones behind the code. So the output path is pinned here.
REM
REM  Why VERSION (P1-7):
REM    *.exe is in .gitignore, so artifacts are never version-controlled and
REM    nothing in git can tell you which build sits in exe\. That is exactly
REM    how a two-milestone-stale exe survived a successful build unnoticed.
REM    VERSION records commit + dirty marker + build time + artifact list.
REM
REM  IMPORTANT: this file must stay pure ASCII.
REM    cmd.exe reads .bat with the console code page (cp936 on a Chinese
REM    Windows); non-ASCII bytes get mangled into bogus commands and the
REM    script dies with confusing errors. Keep all explanation here in English;
REM    the Chinese docs live in README.md / docs\deploy-windows.md.
REM ===================================================================
setlocal enabledelayedexpansion
cd /d %~dp0

echo [1/3] Cleaning previous build output ...
if exist dist rmdir /s /q dist
if exist build\LearningHub rmdir /s /q build\LearningHub

echo [2/3] PyInstaller build (--distpath ..\exe) ...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath ..\exe LearningHub.spec
if errorlevel 1 (
    echo.
    echo [FAILED] PyInstaller returned an error, see the log above.
    exit /b 1
)

echo [3/3] Writing ..\exe\VERSION (commit + artifacts) ...
REM -ExecutionPolicy Bypass: this machine's policy blocks .ps1 by default, and
REM without it step 3 fails with an unrelated-looking "cannot load file" error.
powershell -NoProfile -ExecutionPolicy Bypass -File build-version.ps1
if errorlevel 1 (
    echo.
    echo [WARNING] VERSION could not be written. The exes above are still usable,
    echo          but you lose the "which build is this?" marker - see P1-7.
) else (
    echo.
    echo ---- ..\exe\VERSION ----
    type ..\exe\VERSION
)

echo.
echo [DONE] Artifacts written to ..\exe\ :
dir /b ..\exe\*.exe
exit /b 0