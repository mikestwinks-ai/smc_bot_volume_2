@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
set "LOG=logs\startup_diagnostic_trace.log"
if not exist "logs" mkdir logs
echo.>>"%LOG%"
echo ============================================================>>"%LOG%"
echo STARTUP DIAGNOSTIC RUN | %date% %time%>>"%LOG%"
echo ============================================================>>"%LOG%"

call :ts "STEP 0 | cwd"
cd>>"%LOG%" 2>&1

call :ts "STEP 1 | python --version"
python --version>>"%LOG%" 2>&1
if errorlevel 1 (
  call :ts "STEP 1 FAILED | python not on PATH"
  goto :done
)

call :ts "STEP 2 | before venv activate"
if exist "venv\Scripts\activate.bat" (
  echo [INFO] Activating virtual environment...>>"%LOG%"
  call venv\Scripts\activate.bat
  call :ts "STEP 3 | after venv activate"
) else (
  call :ts "STEP 3 | no venv found"
)

call :ts "STEP 4 | before python main.py"
echo ============================================================>>"%LOG%"
echo   SMC Trading Bot — Starting (diagnostic)>>"%LOG%"
echo   Time: %date% %time%>>"%LOG%"
echo ============================================================>>"%LOG%"

call :ts "STEP 5 | launching python -u main.py (90s max in wrapper)"
venv\Scripts\python.exe -u main.py>>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
call :ts "STEP 6 | python main.py exited"
echo EXIT CODE: %RC%>>"%LOG%"

:done
call :ts "DIAGNOSTIC BATCH COMPLETE"
echo Wrote trace log to %LOG%
type "%LOG%"
endlocal
exit /b 0

:ts
echo [%date% %time%] %~1
echo [%date% %time%] %~1>>"%LOG%"
exit /b 0
