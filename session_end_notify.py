"""
会话结束通知 — 生成有意义的对话总结并通过微信发送
由 Claude Code Stop hook 自动调用
"""
import json, os, datetime, sys

LAST_USER_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\last_user.json")
CHAT_LOG_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\chat_history.jsonl")
NOTIFY_SCRIPT = r"C:\Users\wangzibo\Desktop\wechat_notify.py"
PYTHON = r"C:\Users\wangzibo\AppData\Local\Programs\Python\Python312\python.exe"

def get_recent_chat(n=10):
    """获取最近 n 条聊天记录"""
    if not os.path.exists(CHAT_LOG_FILE):
        return []
    lines = []
    try:
        with open(CHAT_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    lines.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return lines[-n:]


def generate_summary():
    """根据最近聊天记录生成结束通知"""
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M")

    recent = get_recent_chat(30)
    if not recent:
        return "Claude Code 会话已结束。需要我帮忙做什么吗？"

    # 提取关键信息
    user_msgs = [m for m in recent if m.get("direction") == "in" and m.get("from") != "system"]
    claude_msgs = [m for m in recent if m.get("direction") == "out"]

    # 找出项目标签
    projects_mentioned = set()
    for m in recent:
        text = m.get("text", "")
        for proj in ["股票", "体态", "体脂", "论文", "短剧", "VFX"]:
            if proj in text:
                projects_mentioned.add(proj)

    # 统计操作类型
    operations = []
    for m in recent:
        text = m.get("text", "")
        if "[发送文件]" in text:
            operations.append("文件发送")
        if "[执行结果]" in text:
            operations.append("命令执行")
        if "[审批" in text:
            operations.append("权限审批")
        if "已编辑" in text:
            operations.append("代码编辑")

    lines = [f"Claude Code 会话结束 | {time_str}"]

    # 涉及的项目
    if projects_mentioned:
        lines.append(f"涉及项目: {', '.join(sorted(projects_mentioned))}")
    else:
        lines.append("涉及项目: 全局对话")

    # 操作统计
    op_counts = {}
    for op in operations:
        op_counts[op] = op_counts.get(op, 0) + 1
    if op_counts:
        op_summary = ", ".join(f"{op}×{n}" for op, n in op_counts.items())
        lines.append(f"操作: {op_summary}")

    # 最近用户消息
    last_user = None
    for m in reversed(user_msgs[-5:]):
        text = m.get("text", "").strip()
        if text and len(text) > 3:
            last_user = text[:100]
            break

    if last_user:
        lines.append(f"最后讨论: 「{last_user}」")

    # 提问
    lines.append("")
    lines.append("— 继续操作？ —")
    if projects_mentioned:
        proj_list = "、".join(sorted(projects_mentioned))
        lines.append(f"回复「{proj_list}」+ 你的需求，我立即开始")
    else:
        lines.append("回复任意需求，我立即开始处理")
    lines.append("回复「总结」获取详细工作总结")

    return "\n".join(lines)


if __name__ == "__main__":
    summary = generate_summary()

    # 通过 wechat_notify.py 发送
    import subprocess
    result = subprocess.run(
        [PYTHON, NOTIFY_SCRIPT, summary],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode != 0:
        print(f"发送失败: {result.stderr}")
    else:
        print(f"已发送会话总结")
