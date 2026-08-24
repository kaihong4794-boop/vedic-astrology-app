@echo off
cd /d "%~dp0"
echo ============================
echo  Pushing changes to GitHub...
echo ============================
echo.
git add -A
git commit -m "update code"
echo.
echo Pushing (force, this machine's copy wins)...
git push --force
echo.
echo ============================
echo  Done. If you don't see a red "error" line above, it worked.
echo  You can close this window now.
echo ============================
pause
