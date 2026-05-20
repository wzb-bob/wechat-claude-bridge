"""
会话结束通知 — 生成有意义的对话总结并通过微信发送
由 Claude Code Stop hook 自动调用
"""
import json, os, datetime, sys, subprocess, secrets, requests

LAST_USER_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\last_user.json")
CHAT_LOG_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\chat_history.jsonl")
ACCOUNT_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\account.json")

# 加载账号
with open(ACCOUNT_FILE) as f:
    acc = json.load(f)
TOKEN = acc["token"]
BASE_URL = acc["baseUrl"]

# 加载最近用户
user_id = None
ctx = None
try:
    if os.path.exists(LAST_USER_FILE):
        with open(LAST_USER_FILE) as f:
            d = json.load(f)
            user_id = d.get("user_id")
            ctx = d.get("ctx")
            # 检查是否过期（超过30分钟可能需要新消息）
            updated = d.get("updated", "")
except Exception:
    pass


def send_wechat(text: str) -> bool:
    """直接通过 iLink API 发送消息"""
    if not user_id or not ctx:
        return False
    client_id = f"cc-session-{secrets.token_hex(4)}"
    body = json.dumps({
        "msg": {
            "from_user_id": "",
            "to_user_id": user_id,
            "client_id": client_id,
            "message_type": 2,
            "message_state": 2,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
            "context_token": ctx,
        },
        "base_info": {"channel_version": "0.1.0"}
    })
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": "dGVzdA==",
        "Content-Type": "application/json"
    }
    try:
        resp = requests.post(f"{BASE_URL}/ilink/bot/sendmessage",
                             headers=headers, data=body, timeout=10)
        data = resp.json()
        return data.get("ret", 0) == 0
    except Exception:
        return False


def get_recent_chat(n=30):
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

    # 提取用户和Claude的消息
    user_msgs = [m for m in recent if m.get("direction") == "in" and m.get("from") != "system"]
    claude_msgs = [m for m in recent if m.get("direction") == "out"]

    # 统计涉及的项目
    projects_mentioned = set()
    for m in recent:
        text = m.get("text", "")
        for proj in ["股票", "体态", "体脂", "论文", "短剧", "VFX"]:
            if proj in text:
                projects_mentioned.add(proj)

    # 统计操作
    ops = {"文件发送": 0, "命令执行": 0, "权限审批": 0, "代码编辑": 0}
    for m in recent:
        t = m.get("text", "")
        if "[发送文件]" in t: ops["文件发送"] += 1
        if "[执行结果]" in t: ops["命令执行"] += 1
        if "[审批" in t: ops["权限审批"] += 1
        if "已编辑" in t: ops["代码编辑"] += 1

    lines = [f"Claude Code 结束 | {time_str}"]

    if projects_mentioned:
        lines.append(f"项目: {', '.join(sorted(projects_mentioned))}")

    active_ops = [f"{k}×{v}" for k, v in ops.items() if v > 0]
    if active_ops:
        lines.append(f"操作: {', '.join(active_ops)}")

    # 最近用户消息
    for m in reversed(user_msgs[-3:]):
        txt = m.get("text", "").strip()
        if len(txt) > 3:
            lines.append(f"最后讨论: 「{txt[:80]}」")
            break

    lines.append("")
    if projects_mentioned:
        lines.append(f"继续 {', '.join(sorted(projects_mentioned))} 的工作？直接回复即可")
    else:
        lines.append("继续工作？直接回复你的需求")
    lines.append("新需求也直接说，我在微信上等你")

    return "\n".join(lines)


if __name__ == "__main__":
    summary = generate_summary()
    print(summary)

    if user_id and ctx:
        ok = send_wechat(summary)
        if ok:
            print("已发送到微信")
        else:
            print("微信发送失败（token可能过期，下次发消息会刷新）")
    else:
        print("无用户上下文，跳过微信发送")
