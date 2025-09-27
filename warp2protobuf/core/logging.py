#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logging system for Warp API server - 重构版本
使用统一日志管理系统，修复备份机制缺陷
"""

from .unified_logging import LoggerManager

# 获取统一管理的logger
logger = LoggerManager.get_logger('warp_api', 'warp_api.log')

def log(*a):
    """Legacy log function for backward compatibility"""
    logger.info(" ".join(str(x) for x in a))

def set_log_file(log_file_name: str) -> None:
    """重构后的日志文件设置函数"""
    global logger
    logger = LoggerManager.get_logger('warp_api', log_file_name)
    logger.info(f"日志已重定向至: {log_file_name}")

# 向后兼容性：保持原有的setup_logging函数接口
def setup_logging():
    """保持向后兼容的日志设置函数"""
    return logger

# 向后兼容性：保持原有的backup_existing_log函数接口（现在是空操作）
def backup_existing_log():
    """向后兼容函数 - 备份功能现在由统一系统自动处理"""
    pass