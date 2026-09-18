@echo off
REM ============================================================================
REM  Agent Harness - day-to-day launcher for Windows
REM
REM  Verifies the environment, starts the local web server on localhost, opens
REM  your default browser at it, and keeps this window attached to the server so
REM  Ctrl+C stops it cleanly. No administrator rights, no background services.
REM
REM  Usage:
REM    start.bat                 start the web UI on http://localhost:8765
REM    start.bat /port 8899      use a different port
REM    start.bat /cli            run a task in the terminal instead of the UI
REM    start.bat /noopen         start the server but do not open a browser
REM    start.bat /help           show this summary
REM ============================================================================

setlocal EnableExtensions EnableDelayedExpansion

pushd "%~dp0"

set "PROJECT_ROOT=%CD%"
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "DEFAULT_PORT=8765"
set "PORT=%DEFAULT_PORT%"
set "MODE=web"
set "OPEN_BROWSER=1"
set "EXTRA_ARGS="

REM --- arguments --------------------------------------------------------------
:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="/port" (
    if "%~2"=="" (
        echo   [ERROR]   /port needs a number, for example: start.bat /port 8899
        goto :fail
    )
    set "PORT=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="/cli" (
    set "MODE=cli"
    shift
    goto parse_args
)
if /I "%~1"=="/noopen" (
    set "OPEN_BROWSER=0"
    shift
    goto parse_args
)
if /I "%~1"=="/help" goto :usage
if /I "%~1"=="/nopause" (
    set "NO_PAUSE=1"
    shift
    goto parse_args
)
echo   [ERROR]   Unknown option: %~1
goto :usage

:args_done

REM ---------------------------------------------------------------------------
REM  Pre-flight: is the environment actually set up?
REM ---------------------------------------------------------------------------
if not exist "%VENV_PY%" (
    echo.
    echo   [ERROR]   No virtual environment found at .venv
    echo             Nothing is installed yet, so there is nothing to start.
    echo.
    echo             Run setup.bat first  ^(double-click it in Explorer^).
    echo.
    goto :fail
)

"%VENV_PY%" -c "import agent_harness" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [ERROR]   The agent_harness package is missing from .venv
    echo             The installation looks incomplete or corrupted.
    echo.
    echo             Remediation: run setup.bat again to repair it.
    echo.
    goto :fail
)

if "%MODE%"=="cli" goto :run_cli

REM ---------------------------------------------------------------------------
REM  Web UI mode: check the web extra, then start the server
REM ---------------------------------------------------------------------------
"%VENV_PY%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [ERROR]   The web UI dependencies are not installed.
    echo.
    echo             Remediation: run this once, then start.bat again -
    echo               .venv\Scripts\python.exe -m pip install --editable ".[web]"
    echo             Or run a task in the terminal with:  start.bat /cli
    echo.
    goto :fail
)

if "%OPEN_BROWSER%"=="0" set "AGENT_HARNESS_WEB_NO_BROWSER=1"

REM The server prints its URL and opens the browser once it is accepting
REM connections. This window stays attached: Ctrl+C shuts it down cleanly.
"%VENV_PY%" -m agent_harness.web --port %PORT% %EXTRA_ARGS%
set "SERVER_EXIT=%ERRORLEVEL%"

if not "%SERVER_EXIT%"=="0" (
    if not "%SERVER_EXIT%"=="130" (
        echo.
        echo   [ERROR]   The server stopped with exit code %SERVER_EXIT%.
        echo             Common causes: the port is already in use ^(try
        echo             start.bat /port 8899^), or the config file is invalid.
        echo.
        goto :fail
    )
)

echo.
echo   [SUCCESS] Server stopped. No background process was left running.
echo.
popd
if not "%NO_PAUSE%"=="1" pause
exit /b 0

:run_cli
echo.
echo   [INFO]    CLI mode - the web server will not start.
echo             Type a task and press Enter. Ctrl+C stops a running task.
echo.
:cli_prompt
set "TASK="
set /p "TASK=  task^> "
if not defined TASK (
    echo   [INFO]    Nothing entered - exiting.
    popd
    if not "%NO_PAUSE%"=="1" pause
    exit /b 0
)
"%VENV_PY%" -m agent_harness "%TASK%"
echo.
echo   [INFO]    Exit code %ERRORLEVEL%. Output files are in the output folder.
echo.
goto cli_prompt

:usage
echo.
echo   Agent Harness launcher
echo   ----------------------
echo     start.bat                 start the web UI and open your browser
echo     start.bat /port 8899      bind a specific port
echo     start.bat /cli            run tasks in this terminal
echo     start.bat /noopen         start the server without opening a browser
echo     start.bat /help           this message
echo.
popd
if not "%NO_PAUSE%"=="1" pause
exit /b 0

:fail
popd
if not "%NO_PAUSE%"=="1" (
    echo   Press any key to close this window...
    pause >nul
)
exit /b 1
