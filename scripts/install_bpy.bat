@echo off
REM Install bpy from https://download.blender.org/pypi/bpy/ (not PyPI).
REM Picks the wheel matching the venv's Python version + your CPU.
REM Then runs render.py --help as a smoke test.

setlocal

set ROOT=%~dp0..
set PY=

if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PY=%ROOT%\.venv\Scripts\python.exe"
) else (
    where py >nul 2>&1
    if %ERRORLEVEL%==0 (
        set "PY=py -3"
    ) else (
        set "PY=python"
    )
)

echo Using Python: %PY%
%PY% "%ROOT%\scripts\install_bpy.py" %*
if errorlevel 1 goto :error

echo.
echo Smoke test: render.py --help
%PY% "%ROOT%\render.py" --help
if errorlevel 1 goto :error

echo.
echo bpy install finished. Try:
echo     %PY% scripts\make_test_model.py
echo     %PY% render.py test_model -o render.png -v
exit /b 0

:error
echo.
echo install_bpy failed with exit code %ERRORLEVEL%
exit /b %ERRORLEVEL%
