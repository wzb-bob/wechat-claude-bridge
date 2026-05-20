@echo off
REM === 微信指挥中心 · 守护进程 ===
REM 确保桥接始终运行，关闭VS Code/对话框不影响
REM 由 Windows 计划任务每分钟运行一次

set "PYTHON=C:\Users\wangzibo\AppData\Local\Programs\Python\Python312\python.exe"
set "BRIDGE=C:\Users\wangzibo\wechat-claude-bridge\wechat_bridge.py"
set "LOGFILE=C:\Users\wangzibo\bridge_watchdog.log"

REM 日志轮转：超过 1MB 则归档
for %%A in ("%LOGFILE%") do if %%~zA gtr 1048576 (
    move /Y "%LOGFILE%" "%LOGFILE%.old" >nul 2>&1
)

REM 检查桥接是否在运行
curl -s http://127.0.0.1:18760/health >nul 2>&1
if %errorlevel% equ 0 exit /b 0

REM 桥接已断开，重新启动
echo [%date% %time%] 桥接断开，重新启动... >> "%LOGFILE%"
start /b "" "%PYTHON%" "%BRIDGE%" >> "%LOGFILE%" 2>&1
