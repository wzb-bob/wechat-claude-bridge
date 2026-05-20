"""
微信通知助手 — 供 Claude Code 或其他脚本调用，将消息推送到微信
用法:
  python wechat_notify.py "消息内容"
  python wechat_notify.py --project stocklite "消息内容"
  echo "消息" | python wechat_notify.py --pipe
"""
import requests, json, os, sys, time, secrets

ACCOUNT_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\account.json")
LAST_USER_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\last_user.json")

# 读账户
with open(ACCOUNT_FILE) as f:
    acc = json.load(f)

TOKEN = acc["token"]
BASE_URL = acc["baseUrl"]

# 读最新用户上下文
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


def send_text(to_user: str, text: str, context_token: str) -> dict:
    """通过 iLink API 发送文本消息"""
    client_id = f"cc-notify-{secrets.token_hex(4)}"
    body = json.dumps({
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user,
            "client_id": client_id,
            "message_type": 2,
            "message_state": 2,
            "item_list": [
                {"type": 1, "text_item": {"text": text}}
            ],
            "context_token": context_token,
        },
        "base_info": {"channel_version": "0.1.0"}
    })
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": "dGVzdA==",
        "Content-Type": "application/json"
    }
    resp = requests.post(f"{BASE_URL}/ilink/bot/sendmessage",
                         headers=headers, data=body, timeout=10)
    return resp.json()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="微信通知助手")
    parser.add_argument("text", nargs="*", help="要发送的消息")
    parser.add_argument("--project", "-p", default="", help="项目名称标签")
    parser.add_argument("--pipe", action="store_true", help="从 stdin 读取消息")
    args = parser.parse_args()

    if args.pipe:
        text = sys.stdin.read().strip()
    else:
        text = " ".join(args.text).strip()

    if not text:
        print("错误: 消息不能为空", file=sys.stderr)
        sys.exit(1)

    if not user_id or not ctx:
        print("错误: 尚无用户上下文（需要先在微信上给 bot 发一条消息）", file=sys.stderr)
        sys.exit(1)

    # 加项目标签
    prefix = f"【{args.project}】" if args.project else ""
    full_text = f"{prefix}{text}"

    # 微信限制约2000字，超长截断
    if len(full_text) > 1800:
        full_text = full_text[:1780] + "\n...(已截断)"

    result = send_text(user_id, full_text, ctx)
    if result.get("ret", 0) == 0:
        print(f"已发送: {full_text[:80]}...")
    else:
        print(f"发送失败: {result}", file=sys.stderr)
        sys.exit(1)
