@echo off
setlocal EnableDelayedExpansion
set "PYTHONPATH=%~dp0agents"
set "CANDIDATE_FILE=%~dp0candidate.txt"
set "LOG_DIR=%~dp0logs"
set "ENV_FILE=%~dp0agents\.env"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "LOG_FILE=%LOG_DIR%\run_daily_%DATE:~-4%%DATE:~4,2%%DATE:~7,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%.log"

echo [%DATE% %TIME%] Starting run_daily_candidate.bat > "%LOG_FILE%"
echo [%DATE% %TIME%] WorkingDir=%~dp0 >> "%LOG_FILE%"
echo [%DATE% %TIME%] CandidateFile=%CANDIDATE_FILE% >> "%LOG_FILE%"
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

if not exist "%CANDIDATE_FILE%" (
  echo [%DATE% %TIME%] ERROR: Missing candidate.txt at %CANDIDATE_FILE% >> "%LOG_FILE%"
  exit /b 1
)

for /f "usebackq tokens=* delims=" %%C in ("%CANDIDATE_FILE%") do (
  if not "%%C"=="" (
    echo [%DATE% %TIME%] Running candidate_id=%%C >> "%LOG_FILE%"
    python -u -c "import json; from orchestrator import pipeline; provider_config=json.loads('''{\"providers\":[{\"name\":\"theirstack\",\"type\":\"theirstack\",\"enabled\":true,\"api_key_env\":\"THEIRSTACK_API_KEY\",\"payload_overrides\":{}}]}'''); pipeline.run_daily(candidate_id=r'%%C', provider_config=provider_config, limit_to_score=5)" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
      set "EXIT_CODE=!ERRORLEVEL!"
      echo [%DATE% %TIME%] ERROR: Python failed for candidate_id=%%C ExitCode=!EXIT_CODE! >> "%LOG_FILE%"
      exit /b !EXIT_CODE!
    )
  )
)

echo [%DATE% %TIME%] Completed run_daily_candidate.bat >> "%LOG_FILE%"
