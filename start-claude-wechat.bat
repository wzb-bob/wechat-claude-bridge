@echo off
REM === Claude Code + WeChat Channel 自动启动 ===
REM 开机自启(Startup文件夹) + 手动启动均可
REM 支持: 文字对话 / 文件操作 / 发送文件图片视频到微信

cd /d C:\Users\wangzibo

echo [%date% %time%] 启动 Claude Code WeChat Channel...
"C:\Users\wangzibo\AppData\Roaming\npm\claude.cmd" --dangerously-load-development-channels server:wechat-channel --permission-mode bypassPermissions
