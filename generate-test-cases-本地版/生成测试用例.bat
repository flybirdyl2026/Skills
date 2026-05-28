@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo         Test Case Generator
echo ========================================
echo.

set /p doc_keyword=Input keyword to search docx in input/ (partial name):

set match_count=0
set doc_name=
for %%f in ("input\*%doc_keyword%*.docx") do (
    set /a match_count+=1
    set doc_name=%%~nxf
)

if %match_count%==0 (
    echo [ERROR] No docx file matching "%doc_keyword%" found in input/
    pause
    exit /b 1
)

if %match_count% GTR 1 (
    echo.
    echo Multiple files matched:
    set idx=0
    for %%f in ("input\*%doc_keyword%*.docx") do (
        set /a idx+=1
        echo   [!idx!] %%~nxf
    )
    echo.
    set /p doc_name=Enter exact filename from above:
)

echo Using: %doc_name%

set /p output_name=Output xlsx filename in output/ (e.g. cases.xlsx):

echo.
echo Generating test cases, please wait...
echo.

python scripts/generate_cases.py --requirements_file "input/%doc_name%" --output_file "output/%output_name%"

if %errorlevel% == 0 (
    echo.
    echo [DONE] Output: output\%output_name%
) else (
    echo.
    echo [FAILED] Check the log above.
)

echo.
pause
