"""
WeChat iLink Bot <-> DeepSeek API 桥接 (v6 - with notification relay)
支持在微信上操作项目：读文件、写文件、运行命令、搜索代码、发送文件
v6: 内置 HTTP 通知中继，Claude Code 可通过 curl 推送消息到微信
"""
import requests, json, time, os, secrets, subprocess, hashlib, mimetypes, glob as glob_m, re, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from Crypto.Cipher import AES

ACCOUNT_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\account.json")
with open(ACCOUNT_FILE) as f:
    acc = json.load(f)

TOKEN = acc["token"]
BASE_URL = acc["baseUrl"]

API_URL = "https://api.deepseek.com/anthropic/v1/messages"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
API_MODEL = "deepseek-v4-pro"

if not API_KEY:
    print("[致命错误] 请设置环境变量 DEEPSEEK_API_KEY", flush=True)
    print("  set DEEPSEEK_API_KEY=你的DeepSeek密钥", flush=True)
    sys.exit(1)

if not TOKEN:
    print("[致命错误] account.json 中缺少 token", flush=True)
    sys.exit(1)

# HTTP 连接池（复用连接，减少 TCP 握手）
_ilink_session = requests.Session()
_ilink_session.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "AuthorizationType": "ilink_bot_token",
    "X-WECHAT-UIN": "dGVzdA==",
    "Content-Type": "application/json"
})
_ds_session = requests.Session()
_ds_session.headers.update({
    "x-api-key": API_KEY,
    "anthropic-version": "2023-06-01",
    "Content-Type": "application/json"
})

WORK_DIR = os.path.expanduser("~")
CDN_UPLOAD_URL = "https://novac2c.cdn.weixin.qq.com/c2c/upload"
CHANNEL_VERSION = "0.1.0"
NOTIFY_PORT = 18760
LAST_USER_FILE = os.path.expanduser(r"~\.claude\channels\wechat\default\last_user.json")

# 线程安全的最新用户上下文（供 HTTP 通知中继使用）
_notify_lock = threading.Lock()
_latest_user_id = None
_latest_ctx = None

def get_latest_context():
    """获取最新用户上下文（线程安全）"""
    with _notify_lock:
        return _latest_user_id, _latest_ctx

def update_latest_context(user_id, ctx):
    """更新最新用户上下文并持久化"""
    global _latest_user_id, _latest_ctx
    with _notify_lock:
        _latest_user_id = user_id
        _latest_ctx = ctx
    try:
        with open(LAST_USER_FILE, "w") as f:
            json.dump({"user_id": user_id, "ctx": ctx, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    except Exception:
        pass

# 启动时恢复上次上下文
try:
    if os.path.exists(LAST_USER_FILE):
        with open(LAST_USER_FILE) as f:
            d = json.load(f)
            _latest_user_id = d.get("user_id")
            _latest_ctx = d.get("ctx")
            print(f"恢复上次用户: {_latest_user_id[:20]}...", flush=True)
except Exception:
    pass

print(f"Bot: {acc['botId']}", flush=True)
print(f"Work dir: {WORK_DIR}", flush=True)

# ======================== HTTP 通知中继 ========================

class NotifyHandler(BaseHTTPRequestHandler):
    """接收 Claude Code 发来的通知，转发到微信"""
    def do_POST(self):
        if self.path != "/notify":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            text = body.get("text", "")
            user_id, ctx = get_latest_context()
            if not user_id or not ctx:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'{"error":"no user context yet"}')
                return
            result = send_message(user_id, text, ctx)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"status":"sent","result":result}).encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error":str(e)}).encode())

    def do_GET(self):
        if self.path == "/health":
            user_id, ctx = get_latest_context()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "has_user": user_id is not None,
                "user_id": (user_id or "")[:20]
            }).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """静默日志"""
        pass

def start_notify_server():
    """在后台线程启动 HTTP 通知服务器"""
    try:
        server = HTTPServer(("127.0.0.1", NOTIFY_PORT), NotifyHandler)
        print(f"[通知中继] http://127.0.0.1:{NOTIFY_PORT}/notify", flush=True)
        server.serve_forever()
    except OSError as e:
        print(f"[通知中继] 端口 {NOTIFY_PORT} 已被占用，跳过启动: {e}", flush=True)

threading.Thread(target=start_notify_server, daemon=True).start()


# ======================== AES 加密工具 ========================

def aes_ecb_padded_size(raw_size):
    """计算 AES-ECB 加密后的文件大小(含1字节前缀padding)"""
    return ((raw_size + 1 + 15) // 16) * 16


def aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    """AES-128-ECB 加密 (PKCS7 padding)"""
    # 添加1字节前缀(padding标记)
    pad_len = 16 - (len(data) + 1) % 16
    if pad_len == 0:
        pad_len = 16
    padded = bytes([pad_len]) + data + bytes([pad_len] * pad_len)
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(padded)


def get_mime_type(file_path: str) -> str:
    """根据文件扩展名返回 MIME 类型"""
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska", ".mp3": "audio/mpeg", ".wav": "audio/wav",
        ".pdf": "application/pdf", ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".zip": "application/zip", ".rar": "application/x-rar-compressed",
        ".7z": "application/x-7z-compressed", ".txt": "text/plain",
        ".md": "text/markdown", ".py": "text/x-python",
        ".json": "application/json", ".xml": "application/xml",
    }
    return mime_map.get(ext, "application/octet-stream")


# ======================== 文件上传与发送 ========================

def upload_and_send_file(to_user: str, file_path: str, context_token: str) -> str:
    """
    通过 iLink API 上传文件到微信 CDN 并发送
    返回: 成功消息或错误描述
    """
    if not os.path.exists(file_path):
        return f"[错误] 文件不存在: {file_path}"
    if not os.path.isfile(file_path):
        return f"[错误] 不是文件: {file_path}"

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb > 25:
        return f"[错误] 文件过大: {file_size_mb:.1f}MB (微信上限 25MB)"

    try:
        # 1. 读取文件，计算 MD5
        with open(file_path, "rb") as f:
            plaintext = f.read()
    except Exception as e:
        return f"[错误] 读取文件失败: {e}"

    raw_size = len(plaintext)
    raw_md5 = hashlib.md5(plaintext).hexdigest()
    encrypted_size = aes_ecb_padded_size(raw_size)
    filekey = secrets.token_hex(16)
    aeskey = secrets.token_bytes(16)
    mime = get_mime_type(file_path)
    file_name = os.path.basename(file_path)

    # 确定媒体类型
    if mime.startswith("image/"):
        media_type = 1  # IMAGE
        item_type = 2
    elif mime.startswith("video/"):
        media_type = 2  # VIDEO
        item_type = 5
    else:
        media_type = 3  # FILE
        item_type = 4

    print(f"  [upload] {file_name} ({raw_size} bytes, mime={mime}, item_type={item_type})", flush=True)

    # 2. 获取上传 URL
    try:
        resp = _ilink_session.post(
            f"{BASE_URL}/ilink/bot/getuploadurl",
            json={
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": to_user,
                "rawsize": raw_size,
                "rawfilemd5": raw_md5,
                "filesize": encrypted_size,
                "no_need_thumb": True,
                "aeskey": aeskey.hex(),
                "base_info": {"channel_version": CHANNEL_VERSION}
            },
            timeout=15
        )
        data = resp.json()
        upload_param = data.get("upload_param")
        if not upload_param:
            return f"[错误] 获取上传URL失败: {resp.text[:200]}"
    except Exception as e:
        return f"[错误] getuploadurl 请求失败: {e}"

    # 3. 加密文件内容并上传到 CDN
    ciphertext = aes_ecb_encrypt(plaintext, aeskey)

    try:
        cdn_url = f"{CDN_UPLOAD_URL}?encrypted_query_param={requests.utils.quote(upload_param)}&filekey={requests.utils.quote(filekey)}"
        cdn_resp = requests.post(
            cdn_url,
            data=ciphertext,
            headers={"Content-Type": "application/octet-stream"},
            timeout=60
        )
        if not cdn_resp.ok:
            return f"[错误] CDN上传失败: HTTP {cdn_resp.status_code}"
    except Exception as e:
        return f"[错误] CDN上传请求失败: {e}"

    download_param = cdn_resp.headers.get("x-encrypted-param")
    if not download_param:
        return "[错误] CDN响应缺少 x-encrypted-param"

    # 4. 构造媒体引用并发送消息
    import base64
    aes_key_b64 = base64.b64encode(aeskey.hex().encode()).decode()

    media_ref = {
        "encrypt_query_param": download_param,
        "aes_key": aes_key_b64,
        "encrypt_type": 1
    }

    if item_type == 2:  # 图片
        media_item = {"type": 2, "image_item": {"media": media_ref, "mid_size": encrypted_size}}
    elif item_type == 5:  # 视频
        media_item = {"type": 5, "video_item": {"media": media_ref, "video_size": encrypted_size}}
    else:  # 文件
        media_item = {"type": 4, "file_item": {"media": media_ref, "file_name": file_name, "len": str(raw_size)}}

    client_id = f"cc-py-{secrets.token_hex(4)}"
    try:
        resp = _ilink_session.post(
            f"{BASE_URL}/ilink/bot/sendmessage",
            json={
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user,
                    "client_id": client_id,
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [media_item],
                    "context_token": context_token
                },
                "base_info": {"channel_version": CHANNEL_VERSION}
            },
            timeout=15
        )
        data = resp.json()
        if data.get("ret", 0) != 0:
            return f"[错误] 发送失败: {data.get('errmsg', resp.text[:200])}"
        return f"[成功] 文件已发送: {file_name} ({raw_size} bytes)"
    except Exception as e:
        return f"[错误] 发送消息失败: {e}"


# ======================== 工具定义 ========================

TOOLS = [
    {
        "name": "list_files",
        "description": "列出目录中的文件和子目录。用于浏览项目结构。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要列出内容的目录路径。使用 '.' 表示工作目录。"
                },
                "pattern": {
                    "type": "string",
                    "description": "可选的文件名匹配模式，如 '*.py' 或 '*.dxf'"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "read_file",
        "description": "读取文件内容。用于查看代码、配置、日志等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要读取的文件路径"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "写入或创建文件。用于创建新文件或修改现有文件。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要写入的文件路径"
                },
                "content": {
                    "type": "string",
                    "description": "要写入文件的完整内容"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "run_command",
        "description": "在工作目录中执行 shell 命令。用于运行脚本、安装包、git 操作等。禁止使用 rm -rf、format 等破坏性命令。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令。"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "search_content",
        "description": "在文件中搜索文本内容（使用正则表达式）。用于在项目中查找代码、配置、错误信息等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "要搜索的文本或正则表达式模式"
                },
                "path": {
                    "type": "string",
                    "description": "要搜索的目录。使用 '.' 表示工作目录。"
                },
                "file_types": {
                    "type": "string",
                    "description": "可选的文件扩展名过滤器，如 '.py,.json,.js'"
                }
            },
            "required": ["pattern", "path"]
        }
    },
    {
        "name": "edit_file",
        "description": "编辑文件：查找并替换文本。一次替换一处。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要编辑的文件路径"
                },
                "old_string": {
                    "type": "string",
                    "description": "要替换的精确文本（必须与文件中唯一匹配）"
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新文本"
                }
            },
            "required": ["path", "old_string", "new_string"]
        }
    },
    {
        "name": "send_file",
        "description": "发送文件、图片或视频给微信用户。传入本地文件绝对路径，自动上传并发送。支持 jpg/png/gif/mp4/pdf/doc/xlsx/zip 等格式。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要发送的本地文件绝对路径"
                }
            },
            "required": ["path"]
        }
    }
]

SYSTEM_PROMPT = f"""你是通过微信操作的智能编码助手，管理多个项目。你可以浏览文件、读代码、执行命令、发送文件来帮用户操作电脑。

环境：Windows 11（cmd.exe shell），工作目录 {WORK_DIR}

用户的项目：
- 股票: C:/Users/wangzibo/Desktop/stocklite (股票分析App)
- 体态: C:/Users/wangzibo/bodyfat-miniprogram/bodyfit-android (体态分析Android)
- 体脂: C:/Users/wangzibo/bodyfat-miniprogram (体脂率小程序)
- 论文: C:/Users/wangzibo/thesis-workspace (轴向磁通电机论文)
- 短剧: C:/Users/wangzibo/.claude/skills/short-drama-ad-maker (AI短剧广告)
- VFX: C:/Users/wangzibo/rap-mv-scene/vfx-studio (VFX App制作)

工具：
- list_files(path): 列出目录内容
- read_file(path): 读取文件（含行号）
- write_file(path, content): 创建/覆盖文件
- run_command(command): 执行命令（cmd.exe）
- search_content(pattern, path): 搜索文本
- edit_file(path, old_string, new_string): 编辑文件
- send_file(path): 发送文件/图片/视频给用户（自动上传到微信）

规则：
1. 微信回复简洁（300字内），用列表呈现关键信息
2. run_command 优先用 cmd 自带命令，需要 PowerShell 时加 powershell -Command "..." 前缀
3. 查看运行项目：netstat -ano | findstr "端口" + tasklist | findstr "python" 一次搞定
4. 命令超时 60 秒，路径用正斜杠
5. 3 轮工具内必须给出最终回复，不要让用户等
6. 回复用中文，开头注明当前项目名称如【stocklite】
7. 当用户需要查看图片、图表、截图等文件时，主动用 send_file 发送
8. 用户提到特定项目名时自动定位到对应目录，如说"股票"就操作 stocklite 项目"""


# ======================== 工具执行 ========================

def resolve_path(path):
    """解析路径：相对路径基于 WORK_DIR"""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(WORK_DIR, path))


def is_safe_path(path):
    """安全检查：确保路径在用户目录下"""
    resolved = os.path.realpath(resolve_path(path))
    home = os.path.realpath(os.path.expanduser("~"))
    if resolved.startswith(home):
        return True
    desktop = os.path.realpath(os.path.join(home, "Desktop"))
    if resolved.startswith(desktop):
        return True
    return False


FORBIDDEN_COMMANDS = ["rm -rf /", "del /f /s", "format c:", "format d:", "format e:",
                      "shutdown", "restart", "> /dev/sda", "mkfs", "dd if=",
                      ":(){ :|:& };:", "rd /s", "rmdir /s"]

# 无需审批的只读命令（直接执行）
SAFE_COMMANDS = ["dir ", "type ", "findstr ", "where ", "netstat ", "tasklist ", "ver",
                 "echo ", "date ", "time ", "cd ", "set ", "path", "whoami",
                 "python --version", "pip list", "git status", "git log", "git diff",
                 "git branch", "curl ", "cat ", "ls ", "grep ", "head ", "tail "]

# 待审批的操作 {request_id: {user_id, ctx, command, timestamp}}
_pending_permissions = {}
_perm_lock = threading.Lock()
APPROVAL_TIMEOUT = 300  # 5分钟过期


def prune_expired_permissions():
    """清理过期的审批请求"""
    now = time.time()
    with _perm_lock:
        expired = [rid for rid, p in _pending_permissions.items()
                   if now - p.get("timestamp", 0) > APPROVAL_TIMEOUT]
        for rid in expired:
            del _pending_permissions[rid]


def is_safe_command(cmd):
    cmd_lower = cmd.lower()
    for forbidden in FORBIDDEN_COMMANDS:
        if forbidden in cmd_lower:
            return False
    return True


def execute_tool(name, inputs, context_token=""):
    """执行单个工具调用并返回结果"""
    try:
        if name == "list_files":
            path = resolve_path(inputs.get("path", "."))
            if not is_safe_path(path):
                return f"[安全阻止] 路径超出允许范围: {path}"
            pattern = inputs.get("pattern", "")
            if not os.path.exists(path):
                return f"[错误] 路径不存在: {path}"
            if not os.path.isdir(path):
                return f"[错误] 不是目录: {path}"
            items = []
            try:
                for entry in sorted(os.listdir(path)):
                    full = os.path.join(path, entry)
                    if os.path.isdir(full):
                        items.append(f"[目录] {entry}/")
                    else:
                        items.append(f"[文件] {entry}")
            except PermissionError:
                return "[错误] 没有访问权限"
            if pattern:
                import fnmatch
                items = [i for i in items if fnmatch.fnmatch(i.split("] ", 1)[-1].rstrip("/"), pattern)]
            if not items:
                return "(空目录)"
            return "\n".join(items[:100]) + ("\n... (省略了更多条目)" if len(items) > 100 else "")

        elif name == "read_file":
            path = resolve_path(inputs["path"])
            if not is_safe_path(path):
                return f"[安全阻止] 路径超出允许范围: {path}"
            if not os.path.exists(path):
                return f"[错误] 文件不存在: {path}"
            if not os.path.isfile(path):
                return f"[错误] 不是文件: {path}"
            if os.path.getsize(path) > 500 * 1024:
                return f"[错误] 文件大于 500KB，太大了不能读取"
            encodings = ["utf-8", "gbk", "latin-1"]
            for enc in encodings:
                try:
                    with open(path, "r", encoding=enc) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return "[错误] 无法解码文件"
            lines = content.split("\n")
            numbered = "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(lines))
            return f"--- {path} ---\n{numbered}"

        elif name == "write_file":
            path = resolve_path(inputs["path"])
            if not is_safe_path(path):
                return f"[安全阻止] 路径超出允许范围: {path}"
            content = inputs["content"]
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"[成功] 文件已写入: {path} ({len(content)} 字符)"

        elif name == "run_command":
            cmd = inputs["command"]
            if not is_safe_command(cmd):
                return f"[已阻止] 命令包含不安全的操作: {cmd}"
            # 检查是否需要审批
            need_approval = True
            cmd_lower = cmd.lower().strip()
            for safe_prefix in SAFE_COMMANDS:
                if cmd_lower.startswith(safe_prefix.lower()):
                    need_approval = False
                    break
            if need_approval:
                req_id = secrets.token_hex(3)[:5]
                with _perm_lock:
                    _pending_permissions[req_id] = {
                        "user_id": "",  # 稍后由 ask_claude 回填
                        "cmd": cmd,
                        "timestamp": time.time()
                    }
                return f"[需审批] req={req_id} cmd={cmd[:100]}"
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=60, cwd=WORK_DIR, encoding="cp936", errors="replace"
                )
                out = result.stdout.strip()
                err = result.stderr.strip()
                parts = []
                if out:
                    parts.append(out[:4000])
                if err:
                    parts.append(f"[stderr]\n{err[:1000]}")
                if result.returncode != 0:
                    parts.append(f"[返回码: {result.returncode}]")
                return "\n".join(parts) if parts else "(命令执行成功，无输出)"
            except subprocess.TimeoutExpired:
                return "[错误] 命令超时（60秒）"

        elif name == "search_content":
            pattern = inputs["pattern"]
            path = resolve_path(inputs.get("path", "."))
            if not is_safe_path(path):
                return f"[安全阻止] 路径超出允许范围: {path}"
            file_types = inputs.get("file_types", "")
            if not os.path.isdir(path):
                return f"[错误] 不是目录: {path}"
            matches = []
            exts = [e.strip() for e in file_types.split(",") if e.strip()] if file_types else None
            BINARY_EXTENSIONS = {'.pyc', '.pyo', '.exe', '.dll', '.pdb', '.obj', '.lib',
                                 '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico',
                                 '.mp4', '.mov', '.avi', '.mkv', '.mp3', '.wav', '.flac',
                                 '.zip', '.rar', '.7z', '.tar', '.gz', '.pdf',
                                 '.class', '.jar', '.o', '.a', '.so', '.wasm',
                                 '.ttf', '.otf', '.woff', '.woff2', '.eot',
                                 '.bin', '.dat', '.db', '.sqlite', '.sqlite3'}
            import fnmatch as fm
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
                for fname in files:
                    if exts and not any(fname.endswith(ext) for ext in exts):
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in BINARY_EXTENSIONS:
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            for i, line in enumerate(f, 1):
                                if re.search(pattern, line, re.IGNORECASE):
                                    matches.append(f"{fpath}:{i}: {line.strip()[:200]}")
                                    if len(matches) >= 50:
                                        break
                    except Exception:
                        continue
                    if len(matches) >= 50:
                        break
                if len(matches) >= 50:
                    break
            if not matches:
                return f"未找到匹配 '{pattern}' 的内容"
            return "\n".join(matches) + ("\n... (省略了更多结果)" if len(matches) >= 50 else "")

        elif name == "edit_file":
            path = resolve_path(inputs["path"])
            if not is_safe_path(path):
                return f"[安全阻止] 路径超出允许范围: {path}"
            old = inputs["old_string"]
            new = inputs["new_string"]
            if not os.path.exists(path):
                return f"[错误] 文件不存在: {path}"
            encodings = ["utf-8", "gbk", "latin-1"]
            detected_enc = None
            content = None
            for enc in encodings:
                try:
                    with open(path, "r", encoding=enc) as f:
                        content = f.read()
                    detected_enc = enc
                    break
                except UnicodeDecodeError:
                    continue
            if content is None:
                return "[错误] 无法解码文件"
            count = content.count(old)
            if count == 0:
                return f"[错误] 文本未找到: '{old[:80]}'"
            if count > 1:
                return f"[错误] 文本匹配了 {count} 处（必须唯一）: '{old[:80]}'"
            content = content.replace(old, new)
            with open(path, "w", encoding=detected_enc) as f:
                f.write(content)
            return f"[成功] {path} 已编辑 (编码: {detected_enc})"

        elif name == "send_file":
            path = resolve_path(inputs["path"])
            # send_file 需要在主循环中访问 context_token，这里先返回文件路径
            return f"[SENDFILE]{path}"

        else:
            return f"[错误] 未知工具: {name}"

    except Exception as e:
        return f"[异常] {type(e).__name__}: {str(e)}"


# ======================== DeepSeek API ========================

def ask_claude(text, conversation_history=None, user_id=None, ctx=""):
    """
    调用 DeepSeek API，支持无上限 tool_use 循环。
    执行过程中会将通知和进度推送到微信。
    """
    if conversation_history is None:
        messages = []
    else:
        messages = list(conversation_history)

    messages.append({"role": "user", "content": text})

    tool_call_count = 0

    while True:
        body = {
            "model": API_MODEL,
            "max_tokens": 4000,
            "system": SYSTEM_PROMPT,
            "messages": messages,
            "tools": TOOLS
        }

        resp = _ds_session.post(API_URL, json=body, timeout=90)
        if not resp.ok:
            return f"[API错误 HTTP {resp.status_code}] {resp.text[:300]}"

        data = resp.json()

        # 收集回复
        text_parts = []
        tool_uses = []

        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_uses.append(block)

        # 无工具调用 → 最终回复
        if not tool_uses:
            if text_parts:
                return "\n".join(text_parts)
            else:
                return "[空响应]"

        # 有工具调用：
        # 1. 先把模型说的话（通知/询问）发给微信
        progress_text = "\n".join(text_parts).strip()
        if progress_text and user_id:
            send_message(user_id, progress_text, ctx)

        # 2. 构造 assistant 消息
        assistant_content = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                assistant_content.append({"type": "text", "text": block["text"]})
            elif block.get("type") == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block["id"],
                    "name": block["name"],
                    "input": block.get("input", {})
                })
            elif block.get("type") == "thinking":
                assistant_content.append({"type": "thinking", "thinking": block["thinking"]})

        messages.append({"role": "assistant", "content": assistant_content})

        # 3. 执行工具
        tool_results = []
        for tu in tool_uses:
            tool_name = tu["name"]
            tool_input = tu.get("input", {})
            tool_id = tu["id"]
            print(f"  [tool] {tool_name}({json.dumps(tool_input, ensure_ascii=False)[:100]})", flush=True)

            if tool_name == "send_file":
                path = resolve_path(tool_input.get('path', ''))
                result = upload_and_send_file(user_id, path, ctx) if user_id and ctx else "[错误] 缺少用户上下文"
            else:
                result = execute_tool(tool_name, tool_input)
                # 审批请求：立即发微信通知
                if result.startswith("[需审批]") and user_id:
                    parts = result.split(" ", 2)
                    req_id = parts[1].split("=")[1] if len(parts) > 1 else "???"
                    cmd = parts[2].split("=")[1] if len(parts) > 2 else "unknown"
                    approve_msg = f"Claude 想执行命令:\n{cmd[:150]}\n\n回复 yes {req_id} 批准\n回复 no {req_id} 拒绝"
                    send_message(user_id, approve_msg, ctx)
                    with _perm_lock:
                        if req_id in _pending_permissions:
                            _pending_permissions[req_id]["user_id"] = user_id
                            _pending_permissions[req_id]["ctx"] = ctx

            print(f"  [tool_result] {result[:150]}", flush=True)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result
            })

        messages.append({"role": "user", "content": tool_results})

        # 4. 安全检查
        tool_call_count += 1
        if tool_call_count >= 50:
            if user_id:
                send_message(user_id, "已达到最大操作步数(50)，请简化你的请求。", ctx)
            return "[已达最大操作步数]"

        # 滑动窗口：消息接近上限时保留首条+最新消息
        if len(messages) > 36:
            messages[:] = messages[:1] + messages[-30:]


# ======================== iLink 消息收发 ========================

def send_message(user_id, text, context_token=""):
    """按 iLink API 格式发送消息"""
    client_id = f"cc-py-{secrets.token_hex(4)}"
    body = json.dumps({
        "msg": {
            "from_user_id": "",
            "to_user_id": user_id,
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
    resp = _ilink_session.post(f"{BASE_URL}/ilink/bot/sendmessage",
                                data=body, timeout=10)
    return resp.json()


def extract_text(msg):
    """从 item_list 中提取文字内容"""
    parts = []
    for item in msg.get("item_list", []):
        t = item.get("type", 0)
        if t == 1 and item.get("text_item", {}).get("text"):
            parts.append(item["text_item"]["text"])
        elif t == 2:
            parts.append("[图片]")
        elif t == 3:
            parts.append("[视频]")
        elif t == 4:
            fn = item.get("file_item", {}).get("file_name", "文件")
            parts.append(f"[文件: {fn}]")
        elif t == 5:
            parts.append("[视频]")
    return "".join(parts)


# ======================== 主循环 ========================

sync_buf = ""
# 每个用户的对话历史 {user_id: [messages]}
conversations = {}
MAX_HISTORY = 20

print("=== Running (v6 with notification relay + multi-project) ===\n", flush=True)

while True:
    prune_expired_permissions()
    try:
        body = json.dumps({
            "base_info": {"channel_version": "0.1.0"},
            "bot_type": "3",
            "get_updates_buf": sync_buf
        })
        resp = _ilink_session.post(f"{BASE_URL}/ilink/bot/getupdates",
                                    data=body, timeout=40)
        data = resp.json()

        if data.get("get_updates_buf"):
            sync_buf = data["get_updates_buf"]

        for msg in data.get("msgs", []):
            if msg.get("message_type") != 1:
                continue

            user_id = msg.get("from_user_id", "")
            ctx = msg.get("context_token", "")
            text = extract_text(msg)

            if not user_id or not text:
                continue

            # 更新通知中继上下文（供 Claude Code 推送消息）
            update_latest_context(user_id, ctx)

            # ===== 权限审批回复处理 =====
            perm_match = re.match(r'^\s*(yes|no|y|n)\s+([a-f0-9]{5})\s*$', text.strip(), re.IGNORECASE)
            if perm_match:
                action = "allow" if perm_match.group(1).lower().startswith("y") else "deny"
                req_id = perm_match.group(2).lower()
                with _perm_lock:
                    pending = _pending_permissions.pop(req_id, None)
                if pending and pending.get("user_id") and pending["user_id"] != user_id:
                    _pending_permissions[req_id] = pending  # 放回
                    send_message(user_id, "[权限错误] 这不是你的审批请求", ctx)
                    continue
                if pending:
                    if action == "allow":
                        print(f"  [审批通过] {req_id}: {pending['cmd'][:80]}", flush=True)
                        try:
                            result = subprocess.run(
                                pending["cmd"], shell=True, capture_output=True, text=True,
                                timeout=60, cwd=WORK_DIR, encoding="cp936", errors="replace"
                            )
                            out = result.stdout.strip()[:3000]
                            err = result.stderr.strip()[:500]
                            reply = f"[执行结果] {pending['cmd'][:60]}\n"
                            reply += (out or "(无输出)") + ("\n[stderr]\n" + err if err else "")
                        except subprocess.TimeoutExpired:
                            reply = f"[超时] {pending['cmd'][:60]}"
                        except Exception as e:
                            reply = f"[错误] {e}"
                    else:
                        reply = f"[已拒绝] {pending['cmd'][:60]}"
                    send_message(user_id, reply, ctx)
                else:
                    send_message(user_id, f"[权限请求 {req_id} 已过期或不存在]", ctx)
                continue

            print(f"[{msg.get('create_time','')}] {user_id[:30]}: {text[:200]}", flush=True)

            # 获取或创建该用户的对话历史（按用户+项目分上下文）
            # 支持 @项目名 切换项目上下文
            project_key = "__全局__"
            for proj in ["股票", "体态", "体脂", "论文", "短剧", "vfx", "VFX"]:
                if proj in text:
                    project_key = proj
                    break

            conv_key = f"{user_id}:{project_key}"
            if conv_key not in conversations:
                conversations[conv_key] = []

            history = conversations[conv_key]

            # 清理命令：用户发送 "clear" 重置当前项目对话
            if text.strip().lower() in ("clear", "/clear", "重置"):
                conversations[conv_key] = []
                print(f"  -> [对话已重置] {project_key}", flush=True)
                send_message(user_id, f"对话已重置（项目: {project_key}）。", ctx)
                continue

            # 切换项目命令：/project <名称>
            if text.strip().lower().startswith("/project "):
                new_proj = text.strip()[9:].strip()
                project_key = new_proj
                conv_key = f"{user_id}:{project_key}"
                if conv_key not in conversations:
                    conversations[conv_key] = []
                history = conversations[conv_key]
                send_message(user_id, f"已切换到项目: {project_key}", ctx)
                print(f"  -> [切换项目] {project_key}", flush=True)
                continue

            # 文件发送命令：/send <路径>
            if text.strip().lower().startswith("/send "):
                file_path = text.strip()[6:].strip().strip('"')
                file_path = resolve_path(file_path)
                print(f"  [sendfile] {file_path}", flush=True)
                result = upload_and_send_file(user_id, file_path, ctx)
                send_message(user_id, result, ctx)
                print(f"  -> {result}", flush=True)
                continue

            reply = ask_claude(text, history, user_id, ctx)

            # 更新对话历史
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": reply})
            if len(history) > MAX_HISTORY:
                history[:] = history[-(MAX_HISTORY):]

            print(f"  -> {reply[:200]}", flush=True)

            # 微信消息限制约 2000 字，超长分段发送
            if len(reply) > 1800:
                for i in range(0, len(reply), 1800):
                    chunk = reply[i:i+1800]
                    result = send_message(user_id, chunk, ctx)
                    print(f"  -> sent chunk {i//1800+1}: {result}", flush=True)
                    time.sleep(0.5)
            else:
                result = send_message(user_id, reply, ctx)
                print(f"  -> sent: {result}", flush=True)

        had_messages = len(data.get("msgs", [])) > 0
        time.sleep(0.1 if had_messages else 1)

    except requests.exceptions.Timeout:
        continue
    except KeyboardInterrupt:
        print("\nBye!", flush=True)
        break
    except Exception as e:
        print(f"Error: {e}", flush=True)
        time.sleep(3)
