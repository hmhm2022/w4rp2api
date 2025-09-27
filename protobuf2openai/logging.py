#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一的日志配置 - protobuf2openai模块
使用统一日志管理系统
"""

# 使用统一日志管理器
import sys
import os

# 导入父目录的统一日志系统
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from warp2protobuf.core.unified_logging import LoggerManager

# 使用统一管理的logger
logger = LoggerManager.get_logger('protobuf2openai', 'openai_compat.log')