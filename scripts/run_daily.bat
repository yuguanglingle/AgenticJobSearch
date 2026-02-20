@echo off
setlocal EnableDelayedExpansion

set "ROOT_DIR=%~dp0.."
set "PYTHONPATH=%ROOT_DIR%\agents"
set "PROFILE=%~1"
set "PROJECT_CONFIG=%ROOT_DIR%\config\project.json"
set "ENV_FILE=%ROOT_DIR%\agents\.env"

if not defined PROFILE (
  if exist "%PROJECT_CONFIG%" (
    for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "try { (Get-Content -Raw '%PROJECT_CONFIG%') | ConvertFrom-Json | Select-Object -ExpandProperty default_profile } catch { '' }"`) do (
      set "PROFILE=%%A"
    )
  )
)

if "%PROFILE%"=="" (
  set "PROFILE=default"
  echo [run_daily] No default profile found. Using "default". Open Streamlit to create/select a profile.
)

set "PROFILE_CONFIG=%ROOT_DIR%\config\profiles\%PROFILE%.json"
set "LOG_DIR="
set "DB_PATH="

if exist "%PROFILE_CONFIG%" (
  for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "try { (Get-Content -Raw '%PROFILE_CONFIG%') | ConvertFrom-Json | Select-Object -ExpandProperty logs_dir } catch { '' }"`) do (
    set "LOG_DIR=%%A"
  )
  for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "try { (Get-Content -Raw '%PROFILE_CONFIG%') | ConvertFrom-Json | Select-Object -ExpandProperty db_path } catch { '' }"`) do (
    set "DB_PATH=%%A"
  )
)

if "%LOG_DIR%"=="" (
  set "LOG_DIR=%ROOT_DIR%\logs\%PROFILE%"
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "STDOUT_LOG=%LOG_DIR%\stdout.log"
set "STDERR_LOG=%LOG_DIR%\stderr.log"
set "HISTORY_LOG=%LOG_DIR%\run_history.log"

set "PYTHON_EXE=%ROOT_DIR%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python"
)

echo [%DATE% %TIME%] Starting run_daily.bat profile=%PROFILE% >> "%HISTORY_LOG%"
echo [%DATE% %TIME%] WorkingDir=%ROOT_DIR% >> "%HISTORY_LOG%"
echo [%DATE% %TIME%] ProjectConfig=%PROJECT_CONFIG% >> "%HISTORY_LOG%"
echo [%DATE% %TIME%] ProfileConfig=%PROFILE_CONFIG% >> "%HISTORY_LOG%"
echo [%DATE% %TIME%] EnvFile=%ENV_FILE% >> "%HISTORY_LOG%"
echo [%DATE% %TIME%] PythonExe=%PYTHON_EXE% >> "%HISTORY_LOG%"
if not "%DB_PATH%"=="" (
  echo [%DATE% %TIME%] DB_PATH=%DB_PATH% >> "%HISTORY_LOG%"
)

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
        echo [%DATE% %TIME%] WARNING: Skipping empty env var !ENV_KEY! >> "%HISTORY_LOG%"
      )
    )
  )
) else (
  echo [%DATE% %TIME%] WARNING: .env not found at %ENV_FILE% >> "%HISTORY_LOG%"
)

if defined THEIRSTACK_API_KEY (
  echo [%DATE% %TIME%] THEIRSTACK_API_KEY=present >> "%HISTORY_LOG%"
) else (
  echo [%DATE% %TIME%] THEIRSTACK_API_KEY=missing >> "%HISTORY_LOG%"
)

"%PYTHON_EXE%" -m orchestrator.pipeline --mode daily --profile "%PROFILE%" >> "%STDOUT_LOG%" 2>> "%STDERR_LOG%"
set "EXITCODE=%ERRORLEVEL%"

echo [%DATE% %TIME%] Finished run_daily.bat profile=%PROFILE% exit=%EXITCODE% >> "%HISTORY_LOG%"
exit /b %EXITCODE%
