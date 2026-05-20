@echo off
REM === Claude Code + WeChat Channel (手动启动) ===
REM 支持所有 Claude Code 参数，如: claude-with-wechat -p "你好"
REM 文件发送功能已内置在 MCP channel 中 (wechat_send_file 工具)

"C:\Users\wangzibo\AppData\Roaming\npm\claude.cmd" --dangerously-load-development-channels server:wechat-channel %*
