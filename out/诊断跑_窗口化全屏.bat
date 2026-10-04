@echo off
rem ============================================================
rem  P1 diagnostic run (windowed-fullscreen): 60s capture + evidence dump
rem
rem  HOW TO USE
rem    1) double-click this file (keep it next to the HSR exe)
rem    2) switch back to the game within the 15s countdown
rem    3) play for ~1 minute (let the total-damage number move)
rem    4) stop: click the "Stop" button on the panel, or press Ctrl+Alt+Q
rem
rem  OUTPUT (same folder)
rem    out\user_diag.csv      per-frame diagnostics (box / box-source / ink / text)
rem    out\user_frames\*.jpg  one full-screen frame every 3s
rem    (the exe also writes its console output to a run-log .txt next to it)
rem
rem  WHY ASCII-ONLY: cmd.exe parses .bat in the OEM codepage (GBK), so a UTF-8
rem  Chinese filename/echo inside would be mangled -> "file not found".
rem  The exe is therefore located by wildcard instead of by name.
rem ============================================================
chcp 936 >nul
cd /d "%~dp0"
set "EXE="
for %%F in ("%~dp0*.exe") do set "EXE=%%~fF"
if not defined EXE (
    echo [!] No .exe found next to this .bat. Put this file beside the HSR exe.
    pause
    exit /b 1
)
echo.
echo   Target: "%EXE%"
echo   15s countdown, then 60s capture. Switch to the game NOW and play.
echo   Stop: the panel's Stop button, or Ctrl+Alt+Q.
echo.
start /wait "" "%EXE%" --countdown 15 --seconds 60 --overlay --pos 40,40 --dump-diag out\user_diag.csv --dump-frames out\user_frames --dump-frames-every 3
echo.
echo   Done. See the "out" folder beside this file, and the run-log .txt beside the exe.
pause
