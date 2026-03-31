@echo off
:: Publish master -> main (clean distribution branch)
:: Removes dev-only files that end users don't need.
::
:: Usage: Scripts\publish_main.bat

cd /d "%~dp0\.."

echo.
echo ============================================================
echo   Publishing master -> main (clean distribution)
echo ============================================================
echo.

:: Ensure we're on master
for /f "delims=" %%B in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%B"
if not "%BRANCH%"=="master" echo [ERROR] Must be on master branch. & pause & exit /b 1

:: Ensure working tree is clean
git diff --quiet
if %errorlevel% neq 0 echo [ERROR] Uncommitted changes. Commit or stash first. & pause & exit /b 1
git diff --cached --quiet
if %errorlevel% neq 0 echo [ERROR] Staged changes. Commit first. & pause & exit /b 1

echo [1/4] Creating temp branch from master...
git branch -D _dist_temp >nul 2>&1
git checkout -b _dist_temp

echo [2/4] Removing dev-only files...

:: Dev documentation (Claude/Agent instructions)
git rm -r CLAUDE.md 2>nul

:: Dev docs folder (knowledge base, specs, onboarding, tasks, architecture)
git rm -r docs/ 2>nul

:: Build tools (end users don't rebuild)
git rm -r Scripts/ 2>nul
git rm -r patches/ 2>nul

:: Source JS and HTML (end users use the bundle)
git rm -r js/ 2>nul
git rm -r virtual_beamline_nanoprobe_V4_36.html 2>nul
git rm -r virtual_beamline_nanoprobe_V4_35.html 2>nul

:: Ptycho dev files (end users connect to external K4GSR-PTYCHO server)
git rm -r ptycho/ 2>nul

:: Tests and dev configs
git rm -r tests/ 2>nul
git rm -r opi/ 2>nul
git rm -r test_fitting.py 2>nul
git rm -r pyproject.toml 2>nul

:: Research/feedback (internal)
git rm -r Feedback/ 2>nul
git rm -r Research_plan/ 2>nul

:: Paper (internal)
git rm -r paper/ 2>nul

echo        Done.

echo [3/4] Committing and pushing to main...
git commit -m "Distribution: clean release from master" --quiet
git branch -f main _dist_temp

git push origin main --force
echo        Pushed to main.

echo [4/4] Returning to master...
git checkout master --quiet
git branch -D _dist_temp >nul 2>&1

echo.
echo ============================================================
echo   Done! main branch updated with clean distribution.
echo   master branch unchanged.
echo ============================================================
echo.
pause
