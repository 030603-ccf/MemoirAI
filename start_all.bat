@echo off

REM MemoirAI Dev Launcher

setlocal

set CHAT_ROOT=%~dp0

:: Try to find Python automatically (conda env preferred, then PATH)
set PYTHON=
if exist "E:\miniconda3\envs\wechatmsg\python.exe" set PYTHON=E:\miniconda3\envs\wechatmsg\python.exe
if exist "%USERPROFILE%\miniconda3\envs\wechatmsg\python.exe" set PYTHON=%USERPROFILE%\miniconda3\envs\wechatmsg\python.exe
if "%PYTHON%"=="" (
    where python 2>nul | findstr /i python >nul
    if not errorlevel 1 (
        for /f "delims=" %%i in ('where python') do set "PYTHON=%%i"
    )
)
if "%PYTHON%"=="" (
    echo [ERROR] Python not found. Please set PYTHON path in start_all.bat
    pause
    exit /b 1
)
echo ============================================

echo  MemoirAI Dev Mode

echo ============================================

echo.



echo [1/3] Starting backend :8088 ...

start "memoir-backend" cmd /k "cd /d %CHAT_ROOT%\backend && %PYTHON% -m uvicorn api:app --host 0.0.0.0 --port 8088 --reload"

timeout /t 3 /nobreak > nul



echo [2/3] Starting frontend :5173 ...

start "memoir-frontend" cmd /k "cd /d %CHAT_ROOT%\frontend && npm run dev"



echo [3/3] Waiting for frontend ...

set /a wait=0

:wait_loop

timeout /t 2 /nobreak > nul

set /a wait+=2

if %wait% lss 20 (

    echo    waiting %wait% sec ...

    netstat -an | findstr ":5173" > /dev/null 2>&1

    if errorlevel 1 (

        goto wait_loop

    ) else (

        echo    frontend ready!

    )

) else (

    echo    timeout.

)



echo    Opening browser ...

start "" "http://localhost:5173"



echo.

echo ============================================

echo  All started!

echo  API: http://localhost:8088

echo  UI:  http://localhost:5173

echo ============================================

echo.

echo  Close all popup windows to stop.

echo ============================================

echo.

pause

endlocal
