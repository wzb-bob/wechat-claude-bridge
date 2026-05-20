"""
会话启动通知 — Claude Code 会话开始时推送信息到微信
由 Claude Code Start hook 自动调用
"""
import json, os, datetime, sys, secrets, requests

LAST_USER_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\last_user.json")
ACCOUNT_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\account.json")

# 加载账号
with open(ACCOUNT_FILE) as f:
    acc = json.load(f)
TOKEN = acc["token"]
BASE_URL = acc["baseUrl"]

# 加载用户上下文
user_id = None
ctx = None
try:
    if os.path.exists(LAST_USER_FILE):
        with open(LAST_USER_FILE) as f:
            d = json.load(f)
            user_id = d.get("user_id")
            ctx = d.get("ctx")
except Exception:
    pass


def send_wechat(text: str) -> bool:
    if not user_id or not ctx:
        return False
    client_id = f"cc-start-{secrets.token_hex(4)}"
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
        return resp.json().get("ret", -1) == 0
    except Exception:
        return False


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

    send_wechat(msg)
    print(msg)
