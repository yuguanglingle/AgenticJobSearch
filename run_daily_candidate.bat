@echo off
setlocal EnableDelayedExpansion
set "PYTHONPATH=%~dp0agents"
set "ENV_FILE=%~dp0agents\.env"
set "PROJECT_CONFIG=%~dp0config\project.json"
set "PROFILES_DIR=%~dp0config\profiles"

set "DEFAULT_PROFILE="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "try { (Get-Content -Raw '%PROJECT_CONFIG%' | ConvertFrom-Json).default_profile } catch { '' }"`) do (
  set "DEFAULT_PROFILE=%%P"
)
set "DEFAULT_PROFILE=!DEFAULT_PROFILE:"=!"

if not defined DEFAULT_PROFILE (
  echo [%DATE% %TIME%] ERROR: default_profile missing in %PROJECT_CONFIG%
  exit /b 1
)

set "PROFILE_CONFIG=%PROFILES_DIR%\!DEFAULT_PROFILE!.json"
set "LOG_DIR="
for /f "usebackq delims=" %%L in (`powershell -NoProfile -Command "try { $p = (Get-Content -Raw '%PROFILE_CONFIG%' | ConvertFrom-Json); if ($p.logs_dir) { $p.logs_dir } else { '' } } catch { '' }"`) do (
  set "LOG_DIR=%%L"
)
set "LOG_DIR=!LOG_DIR:"=!"
if not defined LOG_DIR (
  set "LOG_DIR=%~dp0logs\!DEFAULT_PROFILE!"
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "LOG_FILE=%LOG_DIR%\run_daily_%DATE:~-4%%DATE:~4,2%%DATE:~7,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%.log"

echo [%DATE% %TIME%] Starting run_daily_candidate.bat > "%LOG_FILE%"
echo [%DATE% %TIME%] WorkingDir=%~dp0 >> "%LOG_FILE%"
echo [%DATE% %TIME%] DefaultProfile=!DEFAULT_PROFILE! >> "%LOG_FILE%"
echo [%DATE% %TIME%] ProfileConfig=%PROFILE_CONFIG% >> "%LOG_FILE%"
echo [%DATE% %TIME%] LogDir=%LOG_DIR% >> "%LOG_FILE%"
echo [%DATE% %TIME%] EnvFile=%ENV_FILE% >> "%LOG_FILE%"

if exist "%ENV_FILE%" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    set "ENV_KEY=%%A"
    set "ENV_VAL=%%B"
    if not "!ENV_KEY!"=="" if /i not "!ENV_KEY:~0,1!"=="#" (
      for %%K in ("!ENV_KEY!") do set "ENV_KEY=%%~K"
      for %%V in ("!ENV_VAL!") do set "ENV_VAL=%%~V"
      if not "!ENV_VAL!"=="" (
        set "!ENV_KEY!=!ENV_VAL!"
      ) else (
        echo [%DATE% %TIME%] WARNING: Skipping empty env var !ENV_KEY! >> "%LOG_FILE%"
      )
    )
  )
) else (
  echo [%DATE% %TIME%] WARNING: .env not found at %ENV_FILE% >> "%LOG_FILE%"
)

if defined DB_PATH (
  set "DB_PATH=!DB_PATH:"=!"
)
if not defined DB_PATH (
  set "DB_PATH=%~dp0agents\data\app.db"
) else if "!DB_PATH!"=="" (
  set "DB_PATH=%~dp0agents\data\app.db"
)
echo [%DATE% %TIME%] DB_PATH=!DB_PATH! >> "%LOG_FILE%"
echo [%DATE% %TIME%] Loading THEIRSTACK_API_KEY from .env >> "%LOG_FILE%"
if not defined THEIRSTACK_API_KEY (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /R /I /C:"^[ 	]*THEIRSTACK_API_KEY[ 	]*=" "%ENV_FILE%"`) do (
    set "THEIRSTACK_API_KEY=%%B"
    goto :_after_key
  )
)
:_after_key
if defined THEIRSTACK_API_KEY (
  set "THEIRSTACK_API_KEY=!THEIRSTACK_API_KEY:"=!"
  for %%V in ("!THEIRSTACK_API_KEY!") do set "THEIRSTACK_API_KEY=%%~V"
)
if defined THEIRSTACK_API_KEY (
  echo [%DATE% %TIME%] THEIRSTACK_API_KEY=present >> "%LOG_FILE%"
) else (
  echo [%DATE% %TIME%] THEIRSTACK_API_KEY=missing >> "%LOG_FILE%"
)

echo [%DATE% %TIME%] Running daily pipeline for default profile >> "%LOG_FILE%"
python -u -m orchestrator.pipeline --mode daily --use-default-profile >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "EXIT_CODE=!ERRORLEVEL!"
  echo [%DATE% %TIME%] ERROR: Python failed ExitCode=!EXIT_CODE! >> "%LOG_FILE%"
  exit /b !EXIT_CODE!
)

echo [%DATE% %TIME%] Completed run_daily_candidate.bat >> "%LOG_FILE%"
