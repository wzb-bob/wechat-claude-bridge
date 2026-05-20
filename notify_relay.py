"""
共享通知中继模块 — 通过桥接的 HTTP 中继发送微信消息
供 session_start_notify.py / session_end_notify.py / wechat_notify.py 共用
"""
import requests, json, sys

RELAY_URL = "http://127.0.0.1:18760/notify"
HEALTH_URL = "http://127.0.0.1:18760/health"


def bridge_is_running() -> bool:
    """检查桥接是否在运行"""
    try:
        resp = requests.get(HEALTH_URL, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def send_via_relay(text: str) -> bool:
    """通过桥接中继发送微信消息，成功返回 True"""
    try:
        resp = requests.post(RELAY_URL, json={"text": text}, timeout=10)
        return resp.status_code == 200
    except requests.exceptions.ConnectionRefusedError:
        print("错误: 桥接未运行，无法发送微信通知", file=sys.stderr)
        print("请先运行 start-wechat-py-bridge.bat", file=sys.stderr)
        return False
    except Exception as e:
        print(f"错误: 通知中继请求失败: {e}", file=sys.stderr)
        return False
