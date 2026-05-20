# 微信指挥中心 · WeChat-Claude Bridge

在微信上通过 AI 远程操控电脑——对话、发文件、执行命令、审批权限，关闭电脑对话框也能用。

## 能力

| 功能 | 说明 |
|------|------|
| 微信聊天 | DeepSeek API 驱动，支持多项目上下文自动切换 |
| 文件发送 | AI 自动调用 send_file，支持图片/视频/文档 |
| 命令执行 | 读文件、写代码、运行命令、搜索项目 |
| 权限审批 | 危险操作自动推送微信确认，回复 yes/no 即可 |
| 通知推送 | 会话结束后自动推送总结到微信 |
| 独立运行 | 关闭 VS Code/对话框不影响，守护进程自动重启 |

## 快速开始

### 1. 配置账号

```bash
cd ~/.claude/channels/wechat
bun setup.ts
# 扫码登录你的微信 bot
```

### 2. 启动桥接

```bash
# Windows
start-wechat-py-bridge.bat

# 或直接运行
python wechat_bridge.py
```

### 3. 在微信中使用

给 bot 发消息即可开始。支持的命令：

| 输入 | 效果 |
|------|------|
| `股票 查看行情` | 切换到股票项目并执行 |
| `论文把终稿发我` | AI 找到文件并发送到微信 |
| `/send "C:\path\to\file.png"` | 直接发送文件 |
| `/project 体态` | 手动切换项目 |
| `clear` | 重置对话 |

## 文件说明

```
wechat_bridge.py      # 主桥接 v6（微信 <-> DeepSeek API）
wechat_notify.py      # 通知助手（从任意位置推送消息到微信）
session_end_notify.py # 会话结束总结通知
bridge_watchdog.bat   # 守护进程（每分钟检测，断开自动重启）
start-wechat-py-bridge.bat  # Windows 启动脚本
wxnotify / wxnotify.bat     # 命令行快捷通知
```

## 多项目路由

在微信中提及项目名即可自动切换上下文：

| 触发词 | 项目 |
|--------|------|
| 股票 | 股票分析 App |
| 体态 | 体态分析 Android |
| 体脂 | 体脂率小程序 |
| 论文 | 学术论文 |
| 短剧 | AI 短剧广告 |
| VFX | VFX App 制作 |

## 依赖

- Python 3.12+
- pycryptodome (`pip install pycryptodome`)
- DeepSeek API key
- 微信 iLink Bot token

## 守护进程

```bash
# 注册 Windows 计划任务（每分钟自动检测）
schtasks /create /tn "WeChatBridgeWatchdog" /tr "C:\Users\wangzibo\bridge_watchdog.bat" /sc minute /mo 1 /f
```
