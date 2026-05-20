"""
会话结束通知 — 生成有意义的对话总结并通过微信发送
由 Claude Code Stop hook 自动调用
"""
import os, datetime, sys

# 将 repo 目录加入 path，以便导入 notify_relay
REPO_DIR = r"C:\Users\wangzibo\wechat-claude-bridge"
sys.path.insert(0, REPO_DIR)
import notify_relay

SESSIONS_DIR = os.path.expanduser(r"~\.claude\sessions")


def generate_summary():
    """生成有意义的会话结束通知"""
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    # 检测项目
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

    # 统计今天的会话数
    session_count = 0
    try:
        if os.path.exists(SESSIONS_DIR):
            for fname in os.listdir(SESSIONS_DIR):
                fpath = os.path.join(SESSIONS_DIR, fname)
                if os.path.isfile(fpath):
                    mtime = os.path.getmtime(fpath)
                    if datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d") == today_str:
                        session_count += 1
    except Exception:
        pass

    lines = [f"Claude Code 会话结束 | {time_str}"]
    lines.append(f"项目: {project_name}")
    lines.append(f"目录: {cwd}")

    if session_count > 0:
        lines.append(f"今日已进行 {session_count} 次会话")

    lines.append("")
    lines.append(f"继续 {project_name} 的工作？直接回复即可")
    lines.append("新需求也直接说，我在微信上等你")

    return "\n".join(lines)


if __name__ == "__main__":
    summary = generate_summary()
    print(summary)

    ok = notify_relay.send_via_relay(summary)
    if ok:
        print("已发送到微信")
    else:
        print("微信发送失败（桥接未运行或用户未连接）", file=sys.stderr)
