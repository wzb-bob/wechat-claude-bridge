"""
会话启动通知 — Claude Code 会话开始时推送信息到微信
由 Claude Code Start hook 自动调用
"""
import json, os, datetime, sys

# 将 repo 目录加入 path，以便导入 notify_relay
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.join(os.path.dirname(REPO_DIR), "wechat-claude-bridge")
if not os.path.exists(os.path.join(REPO_DIR, "notify_relay.py")):
    REPO_DIR = r"C:\Users\wangzibo\wechat-claude-bridge"
sys.path.insert(0, REPO_DIR)
import notify_relay


if __name__ == "__main__":
    now = datetime.datetime.now()
    time_str = now.strftime("%m/%d %H:%M")

    # 尝试获取项目信息
    cwd = os.getenv("CLAUDE_CWD", os.getcwd())
    project_name = "全局"
    proj_map = {
        "stocklite": "股票", "bodyfit": "体态", "bodyfat": "体脂",
        "thesis": "论文", "short-drama": "短剧", "vfx": "VFX"
    }
    for key, name in proj_map.items():
        if key in cwd.lower():
            project_name = name
            break

    msg = f"Claude Code 已启动 | {time_str}\n项目: {project_name}\n目录: {cwd}\n\n回复此消息即可下达指令，操作此项目"

    ok = notify_relay.send_via_relay(msg)
    if ok:
        print(f"[成功] 已发送到微信: {msg[:80]}...")
    else:
        print(msg)
        print("[失败] 微信通知发送失败（桥接未运行或用户未连接）", file=sys.stderr)
