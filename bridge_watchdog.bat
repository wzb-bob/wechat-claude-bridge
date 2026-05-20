@echo off
REM === 微信指挥中心 · 守护进程 ===
REM 确保桥接始终运行，关闭VS Code/对话框不影响
REM 加入 Windows 计划任务每分钟运行一次

cd /d C:\Users\wangzibo

REM 检查桥接是否在运行
curl -s http://127.0.0.1:18760/health >nul 2>&1
if %errorlevel% equ 0 (
    exit /b 0
)

REM 桥接已断开，重新启动
echo [%date% %time%] 桥接断开，重新启动... >> C:\Users\wangzibo\bridge_watchdog.log
start /b C:\Users\wangzibo\AppData\Local\Programs\Python\Python312\python.exe C:\Users\wangzibo\Desktop\wechat_bridge.py >> C:\Users\wangzibo\bridge_watchdog.log 2>&1
