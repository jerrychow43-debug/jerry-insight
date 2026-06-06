import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import requests
except ModuleNotFoundError:
    requests = None

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args, **kwargs):
        return False


load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()

EXECUTOR = ThreadPoolExecutor(max_workers=4)


def get_webhook():
    return os.getenv("DINGTALK_WEBHOOK") or os.getenv("DING_WEBHOOK") or ""


def send_dingtalk_sync(title, content):
    webhook = get_webhook()
    if not webhook:
        print("FastAPI DingTalk skipped: DINGTALK_WEBHOOK not configured")
        return {"errcode": -1, "errmsg": "missing webhook"}
    if requests is None:
        print("FastAPI DingTalk skipped: requests is not installed")
        return {"errcode": -2, "errmsg": "requests not installed"}

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"## {title}\n\n{content}",
        },
    }
    try:
        response = requests.post(
            webhook,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json;charset=utf-8"},
            timeout=5,
        )
        print(f"FastAPI DingTalk response: {response.text}")
        return response.json()
    except Exception as err:
        print(f"FastAPI DingTalk failed: {err}")
        return {"errcode": -3, "errmsg": str(err)}


def notify_async(title, content):
    EXECUTOR.submit(send_dingtalk_sync, title, content)
