from __future__ import annotations

import os
from dotenv import load_dotenv

# 确保.env文件被加载
load_dotenv()

BRIDGE_BASE_URL = os.getenv("WARP_BRIDGE_URL", f"http://127.0.0.1:{os.getenv('WARP_SERVER_PORT', '8000')}")
FALLBACK_BRIDGE_URLS = [
    BRIDGE_BASE_URL,
    f"http://127.0.0.1:{os.getenv('WARP_SERVER_PORT', '8000')}",
]

WARMUP_INIT_RETRIES = int(os.getenv("WARP_COMPAT_INIT_RETRIES", "10"))
WARMUP_INIT_DELAY_S = float(os.getenv("WARP_COMPAT_INIT_DELAY", "0.5"))
WARMUP_REQUEST_RETRIES = int(os.getenv("WARP_COMPAT_WARMUP_RETRIES", "3"))
WARMUP_REQUEST_DELAY_S = float(os.getenv("WARP_COMPAT_WARMUP_DELAY", "1.5")) 