"""
微信通知助手 — 供 Claude Code 或其他脚本调用，将消息推送到微信
用法:
  python wechat_notify.py "消息内容"
  python wechat_notify.py --project stocklite "消息内容"
  echo "消息" | python wechat_notify.py --pipe
"""
import os, sys

# 将 repo 目录加入 path，以便导入 notify_relay
REPO_DIR = r"C:\Users\wangzibo\wechat-claude-bridge"
sys.path.insert(0, REPO_DIR)
import notify_relay


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

    # 加项目标签
    prefix = f"【{args.project}】" if args.project else ""
    full_text = f"{prefix}{text}"

    # 微信限制约2000字，超长截断
    if len(full_text) > 1800:
        full_text = full_text[:1780] + "\n...(已截断)"

    if not notify_relay.bridge_is_running():
        print("错误: 桥接未运行（请先启动 start-wechat-py-bridge.bat）", file=sys.stderr)
        sys.exit(1)

    ok = notify_relay.send_via_relay(full_text)
    if ok:
        print(f"已发送: {full_text[:80]}...")
    else:
        print("发送失败", file=sys.stderr)
        sys.exit(1)
