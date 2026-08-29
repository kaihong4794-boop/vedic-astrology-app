@echo off
cd /d "%~dp0"
echo ============================
echo  Pushing changes to GitHub...
echo ============================
echo.
git add -A
git commit -m "update code"
echo.
echo Pushing...
git push
if errorlevel 1 (
    echo.
    echo ============================
    echo  Something went wrong - see the red text above.
    echo  Don't worry, your changes are safe on this computer,
    echo  nothing was lost. Copy this whole window's text and
    echo  send it to Claude so it can help fix it.
    echo ============================
) else (
    echo.
    echo ============================
    echo  Done. It worked - you can close this window now.
    echo ============================
)
pause
