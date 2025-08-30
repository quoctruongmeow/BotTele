# file: check_live_sync.py
import requests
from typing import Literal

Result = Literal["live", "die", "error"]
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"

def check_live(uid: str, timeout: float = 10.0) -> Result:
    """
    Kiểm tra LIVE/DIE qua graph.facebook (ảnh profile redirect=false).
    Trả về: 'live' | 'die' | 'error' (không trả None).
    Thuật toán: body có 'height' & 'width' => live; có body nhưng thiếu => die; lỗi => error.
    """
    url = f"https://graph.facebook.com/{uid}/picture"
    headers = {
        "Connection": "keep-alive",
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = requests.get(url, params={"redirect": "false"}, headers=headers, timeout=timeout)
        body = r.text or ""
        if body:
            return "live" if ("height" in body and "width" in body) else "die"
    except Exception:
        pass
    return "error"
