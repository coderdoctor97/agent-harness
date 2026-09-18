@echo off
REM ============================================================================
REM  Agent Harness - one-time setup for Windows
REM
REM  Checks the runtimes this project needs, creates a virtual environment,
REM  installs the package (plus the web UI and dev extras), and copies the
REM  environment template. Safe to re-run: every step is idempotent.
REM
REM  Package: agent-harness (PRD G6 - runs entirely locally)
REM  Usage:   double-click in Explorer, or:  setup.bat
REM           setup.bat /nopause        (used by CI; never waits for a key)
REM ============================================================================

setlocal EnableExtensions EnableDelayedExpansion

REM --- working directory: always the folder this script lives in --------------
pushd "%~dp0"

set "PAUSE_AT_END=1"
if /I "%~1"=="/nopause" set "PAUSE_AT_END=0"

set "PROJECT_ROOT=%CD%"
set "VENV_DIR=%PROJECT_ROOT%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "MIN_PY_MAJOR=3"
set "MIN_PY_MINOR=9"
set "EXIT_CODE=0"

call :banner

REM ---------------------------------------------------------------------------
REM  1. Git (optional, but every contributor path needs it)
REM ---------------------------------------------------------------------------
call :info "Checking Git..."
where git >nul 2>&1
if errorlevel 1 (
    call :warn "Git was not found on PATH."
    echo        Installing from a ZIP still works; only cloning and version
    echo        control need Git. Get it from https://git-scm.com/download/win
) else (
    for /f "delims=" %%v in ('git --version 2^>nul') do call :success "%%v"
)

REM ---------------------------------------------------------------------------
REM  2. Python 3.9+ (required) -- prefers the Windows launcher when installed
REM ---------------------------------------------------------------------------
call :info "Checking Python %MIN_PY_MAJOR%.%MIN_PY_MINOR% or newer..."

set "PY_CMD="
py -%MIN_PY_MAJOR%.%MIN_PY_MINOR% -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -%MIN_PY_MAJOR%.%MIN_PY_MINOR%"
) else (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=python"
    ) else (
        python3 -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=python3"
    )
)

if not defined PY_CMD (
    call :error "Python is not installed, or not on PATH."
    echo        Remediation:
    echo          1. Install Python %MIN_PY_MAJOR%.%MIN_PY_MINOR%+ from https://www.python.org/downloads/windows/
    echo          2. On the first installer screen, tick "Add python.exe to PATH".
    echo          3. Close this window, open a NEW one, and run setup.bat again.
    set "EXIT_CODE=1"
    goto :finish
)

for /f "delims=" %%v in ('%PY_CMD% -c "import sys; print('Python %%d.%%d.%%d' %% sys.version_info[:3])" 2^>nul') do set "PY_VERSION=%%v"
%PY_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (%MIN_PY_MAJOR%, %MIN_PY_MINOR%) else 1)"
if errorlevel 1 (
    call :error "Found !PY_VERSION!, but this project requires %MIN_PY_MAJOR%.%MIN_PY_MINOR% or newer."
    echo        Remediation: install a newer Python and re-run setup.bat.
    set "EXIT_CODE=1"
    goto :finish
)
call :success "!PY_VERSION! (!PY_CMD!)"

REM ---------------------------------------------------------------------------
REM  3. Virtual environment -- create once, reuse after that (idempotent)
REM ---------------------------------------------------------------------------
if exist "%VENV_PY%" (
    call :success "Virtual environment already present (.venv) - reusing it."
) else (
    call :info "Creating virtual environment in .venv ..."
    %PY_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        call :error "Could not create the virtual environment."
        echo        Remediation: check free disk space and that you can write to
        echo        this folder, then run setup.bat again.
        set "EXIT_CODE=1"
        goto :finish
    )
    call :success "Virtual environment created."
)

REM ---------------------------------------------------------------------------
REM  4. Dependencies -- upgrade pip, then install the package with extras
REM ---------------------------------------------------------------------------
call :info "Upgrading pip inside the virtual environment..."
"%VENV_PY%" -m pip install --quiet --upgrade pip
if errorlevel 1 (
    call :warn "pip upgrade failed; continuing with the existing pip."
) else (
    call :success "pip is up to date."
)

REM Editable install so agent_harness imports from this folder, not a copy.
REM Extras: [web] = the local browser UI, [dev] = tests, lint and type checks.
set "INSTALL_TARGET=.[web,dev]"
call :info "Installing dependencies (%INSTALL_TARGET%) - first run downloads ~100 MB..."
"%VENV_PY%" -m pip install --quiet --editable "%INSTALL_TARGET%"
if errorlevel 1 (
    call :error "Dependency installation failed."
    echo        Remediation: run the same command without the quotes to see the
    echo        full log:
    echo            .venv\Scripts\python.exe -m pip install --editable "%INSTALL_TARGET%"
    echo        A corporate proxy or an offline network is the usual cause.
    set "EXIT_CODE=1"
    goto :finish
)
call :success "Dependencies installed."

REM ---------------------------------------------------------------------------
REM  5. Environment template -- copy only when no local file exists
REM ---------------------------------------------------------------------------
if exist "%PROJECT_ROOT%\.env" (
    call :success ".env already exists - leaving your configuration untouched."
) else if exist "%PROJECT_ROOT%\.env.example" (
    copy /y "%PROJECT_ROOT%\.env.example" "%PROJECT_ROOT%\.env" >nul
    if errorlevel 1 (
        call :warn "Could not copy .env.example to .env; add it manually."
    ) else (
        call :success "Created .env from .env.example  ^<- add your API key here."
    )
) else (
    call :warn "No .env.example found; skipping the environment template."
)

REM ---------------------------------------------------------------------------
REM  6. Configuration file -- created only when missing
REM ---------------------------------------------------------------------------
if exist "%PROJECT_ROOT%\config.yaml" (
    call :success "config.yaml already exists - keeping it as is."
) else (
    "%VENV_PY%" -c "from agent_harness.config import Config; Config().to_file('config.yaml')" >nul 2>&1
    if errorlevel 1 (
        call :info "Writing a default config.yaml ..."
        >"%PROJECT_ROOT%\config.yaml" echo # Generated by setup.bat - safe to edit.
        >>"%PROJECT_ROOT%\config.yaml" echo llm:
        >>"%PROJECT_ROOT%\config.yaml" echo   provider: openai
        >>"%PROJECT_ROOT%\config.yaml" echo   model: gpt-4o
        >>"%PROJECT_ROOT%\config.yaml" echo   api_key_env: OPENAI_API_KEY
        call :success "config.yaml written with documented defaults."
    ) else (
        call :success "config.yaml written with documented defaults."
    )
)

REM ---------------------------------------------------------------------------
REM  7. Final self-check -- the install is only "done" if this passes
REM ---------------------------------------------------------------------------
call :info "Running the post-install self-check..."
"%VENV_PY%" -c "import agent_harness, sys; print(agent_harness.__version__)" >nul 2>&1
if errorlevel 1 (
    call :error "The package installed but cannot be imported."
    echo        Remediation: run setup.bat again; if it persists, delete the
    echo        .venv folder and re-run to get a clean install.
    set "EXIT_CODE=1"
    goto :finish
)

"%VENV_PY%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    call :warn "The web UI dependencies are missing; start.bat will run the CLI only."
    echo        Fix with: .venv\Scripts\python.exe -m pip install --editable ".[web]"
) else (
    call :success "Web UI dependencies present."
)

call :success "Setup complete."
echo.
echo   Next steps
echo   ----------
echo     start.bat            launch the local UI in your browser
echo     start.bat /cli       run tasks in the terminal instead
echo     .venv\Scripts\python.exe -m pytest    run the test suite
echo.
echo   Add your API key to .env before the first real task.

:finish
if "%EXIT_CODE%"=="0" (
    call :blank
    echo   [SUCCESS] Everything is ready.
) else (
    call :blank
    echo   [ERROR] Setup did not finish. Read the message above, fix it, and re-run.
)

popd
if "%PAUSE_AT_END%"=="1" (
    echo.
    pause
)
exit /b %EXIT_CODE%

REM ===========================================================================
REM  Helpers
REM ===========================================================================

:banner
echo.
echo   ==========================================================================
echo    Agent Harness - Windows setup
echo    Local-first autonomous agent runtime
echo   ==========================================================================
echo.
exit /b 0

:info
echo   [INFO]    %~1
exit /b 0

:success
echo   [SUCCESS] %~1
exit /b 0

:warn
echo   [WARN]    %~1
exit /b 0

:error
echo   [ERROR]   %~1
exit /b 0

:blank
echo.
exit /b 0
