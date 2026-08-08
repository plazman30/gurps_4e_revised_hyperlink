@echo off
REM Double-click setup for the GURPS PDF Hyperlinker (Windows).
REM
REM Installs Python via winget if it's missing, then installs the one
REM required Python package. Safe to run more than once.

setlocal
cd /d "%~dp0"

echo ==================================================
echo  GURPS PDF Hyperlinker - Setup
echo ==================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python not found. Attempting to install it automatically via winget...
    echo.
    where winget >nul 2>nul
    if %errorlevel% neq 0 (
        echo.
        echo Couldn't find "winget" ^(Windows' built-in installer tool^) to install
        echo Python automatically. This usually just means Windows needs updating.
        echo.
        echo Please install Python manually instead:
        echo   1. Go to https://www.python.org/downloads/
        echo   2. Download and run the installer
        echo   3. IMPORTANT: check the box "Add python.exe to PATH" before
        echo      clicking Install Now
        echo   4. Run this setup script again afterward
        echo.
        pause
        exit /b 1
    )

    winget install -e --id Python.Python.3.12
    echo.
    echo Python was just installed. Please CLOSE this window, open this
    echo folder again, and double-click setup.bat one more time so Windows
    echo picks up the change.
    echo.
    pause
    exit /b 0
) else (
    echo Python already installed:
    python --version
)

echo.
echo Installing the required Python package ^(PyMuPDF^)...
python -m pip install -r requirements.txt

echo.
echo ==================================================
echo  Setup complete!
echo.
echo  Example of running the tool on a book:
echo    python hyperlink_pdf.py YourBook.pdf YourBook_linked.pdf
echo ==================================================
echo.
pause
