@echo off
REM Camera Recording Tool Launcher
REM This script activates the Python virtual environment and starts the recording program

echo ========================================
echo    FLIR Camera Recording Tool
echo ========================================
echo.

REM Change to the script's directory
cd /d "%~dp0"

REM Use Python to read VENV_PATH from config.py
for /f "delims=" %%i in ('python -c "import sys; sys.path.insert(0, '.'); from config import VENV_PATH; print(VENV_PATH if VENV_PATH is not None else 'NONE')"') do set VENV_PATH=%%i

REM Check if VENV_PATH is None or empty
if "%VENV_PATH%"=="NONE" (
    echo Using system Python ^(no virtual environment^)
    echo.
    goto :skip_venv
)

if "%VENV_PATH%"=="" (
    echo ERROR: Could not read VENV_PATH from config.py
    echo Using default: env_camera
    set "VENV_PATH=env_camera"
)

REM Convert relative path to absolute if needed
if "%VENV_PATH:~0,3%"=="../" (
    set "VENV_PATH=%~dp0..\%VENV_PATH:~3%"
) else if "%VENV_PATH:~0,2%"==".\" (
    set "VENV_PATH=%~dp0%VENV_PATH:~2%"
) else if not "%VENV_PATH:~1,1%"==":" (
    set "VENV_PATH=%~dp0%VENV_PATH%"
)

echo Using virtual environment: %VENV_PATH%
echo.

REM Check if virtual environment exists
if not exist "%VENV_PATH%\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at %VENV_PATH%!
    echo Please check VENV_PATH in config.py and ensure the environment exists.
    echo.
    pause
    exit /b 1
)

REM Activate virtual environment
call "%VENV_PATH%\Scripts\activate.bat"

REM Check if activation was successful
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment.
    echo.
    pause
    exit /b 1
)

echo Virtual environment activated successfully.

:skip_venv
echo Starting camera recorder...
echo.

REM Run the main recorder script with all arguments passed to the batch file
python src\main_recorder.py %*

echo.
echo ========================================
echo Recording complete!
echo Press any key to exit...
echo ========================================
pause
