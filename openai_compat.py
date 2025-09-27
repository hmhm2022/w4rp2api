#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Chat Completions compatible server (system-prompt flavored)

Startup entrypoint that exposes the modular app implemented in protobuf2openai.
"""

from __future__ import annotations

import os

from protobuf2openai.app import app  # FastAPI app


if __name__ == "__main__":
    import uvicorn
    # OpenAI兼容层不需要在启动时刷新JWT，由server.py统一管理JWT
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("OPENAI_SERVER_PORT", "8010")),
        log_level="info",
    )
