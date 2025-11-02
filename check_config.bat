@echo off
echo ================================================
echo Project Siesta - Configuration Checker
echo ================================================
echo.

REM Check if .env file exists
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo.
    echo Please create a .env file in the project root directory.
    echo You can copy sample.env to .env and fill in your credentials.
    echo.
    echo See SETUP_GUIDE.md for detailed instructions.
    pause
    exit /b 1
)

echo [OK] .env file found
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.8 or higher
    pause
    exit /b 1
)

echo [OK] Python is installed
python --version
echo.

REM Check if virtual environment exists
if not exist ".venv" (
    echo [INFO] Virtual environment not found. Creating one...
    python -m venv .venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment found
)
echo.

REM Activate virtual environment and install dependencies
echo [INFO] Activating virtual environment...
call .venv\Scripts\activate.bat
echo.

echo [INFO] Checking dependencies...
pip install -r requirements.txt --quiet
echo [OK] Dependencies checked/installed
echo.

echo ================================================
echo Configuration Check Complete!
echo ================================================
echo.
echo Next steps:
echo 1. Edit .env file with your Telegram credentials
echo 2. Ensure MongoDB is running
echo 3. Run: python -m bot
echo.
echo See SETUP_GUIDE.md for detailed setup instructions
echo.
pause

