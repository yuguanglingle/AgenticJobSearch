@echo off
setlocal
set "PYTHONPATH=%~dp0agents"
set "CANDIDATE_FILE=%~dp0candidate.txt"
if not exist "%CANDIDATE_FILE%" (
  echo Missing candidate.txt at %CANDIDATE_FILE%
  exit /b 1
)

for /f "usebackq tokens=* delims=" %%C in ("%CANDIDATE_FILE%") do (
  if not "%%C"=="" (
    echo Running candidate_id=%%C
    python -c "import json; from orchestrator import pipeline; provider_config=json.loads('''{\"providers\":[{\"name\":\"theirstack\",\"type\":\"theirstack\",\"enabled\":true,\"api_key_env\":\"THEIRSTACK_API_KEY\",\"payload_overrides\":{}}]}'''); pipeline.run_daily(candidate_id=r'%%C', provider_config=provider_config, limit_to_score=5)"
  )
)
