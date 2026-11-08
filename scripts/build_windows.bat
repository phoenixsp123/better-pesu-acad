@echo off
REM ==========================================
REM  Building Better PESU Acad for Windows
REM ==========================================

echo Building Better PESU Acad for Windows...

if exist venv\Scripts\pyinstaller.exe (
    set PYINSTALLER=venv\Scripts\pyinstaller.exe
) else (
    set PYINSTALLER=pyinstaller
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

%PYINSTALLER% --noconfirm --clean BetterPESU.spec

if exist dist\BetterPESU\BetterPESU.exe (
    echo.
    echo ==========================================
    echo Build Succeeded!
    echo Executable located at: dist\BetterPESU\BetterPESU.exe
    echo ==========================================
) else (
    echo Build failed: executable not found.
    exit /b 1
)
