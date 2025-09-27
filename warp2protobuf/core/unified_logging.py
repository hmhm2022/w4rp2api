#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志系统配置模块
解决双重日志系统冲突，支持环境变量配置
"""
import logging
import os
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass

@dataclass
class LogConfig:
    """日志配置数据类"""
    level: int = logging.INFO
    console_level: int = logging.INFO  
    file_level: int = logging.DEBUG
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5
    format_type: str = 'detailed'
    enable_rotation: bool = True
    log_directory: str = 'logs'
    
    @classmethod
    def from_env(cls) -> 'LogConfig':
        """从环境变量加载配置"""
        return cls(
            level=get_log_level('LOG_LEVEL'),
            console_level=get_log_level('LOG_CONSOLE_LEVEL'),
            file_level=get_log_level('LOG_FILE_LEVEL'),
            max_file_size=int(os.getenv('LOG_MAX_FILE_SIZE', '10485760')),
            backup_count=int(os.getenv('LOG_BACKUP_COUNT', '5')),
            format_type=os.getenv('LOG_FORMAT', 'detailed'),
            enable_rotation=os.getenv('LOG_ENABLE_ROTATION', 'true').lower() == 'true',
            log_directory=os.getenv('LOG_DIRECTORY', 'logs')
        )

class LoggerManager:
    """统一的日志管理器 - 单例模式"""
    _instances: Dict[str, logging.Logger] = {}
    _initialized = False
    _config: LogConfig = None
    
    @classmethod
    def get_logger(cls, name: str, log_file: Optional[str] = None) -> logging.Logger:
        """获取或创建logger实例（单例模式）"""
        if not cls._initialized:
            cls.setup_unified_logging()
        
        cache_key = f"{name}:{log_file or 'default'}"
        if cache_key not in cls._instances:
            cls._instances[cache_key] = cls._create_logger(name, log_file)
        return cls._instances[cache_key]
    
    @classmethod
    def _create_logger(cls, name: str, log_file: Optional[str]) -> logging.Logger:
        """创建新的logger实例"""
        logger = logging.getLogger(name)
        logger.setLevel(cls._config.level)
        
        # 清除现有handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # 创建文件handler
        if log_file:
            log_path = Path(cls._config.log_directory) / log_file
            file_handler = SafeRotatingFileHandler(
                log_path,
                maxBytes=cls._config.max_file_size,
                backupCount=cls._config.backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(cls._config.file_level)
            file_handler.setFormatter(get_formatter(cls._config.format_type))
            logger.addHandler(file_handler)
        
        # 创建控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(cls._config.console_level)
        console_handler.setFormatter(get_formatter(cls._config.format_type))
        logger.addHandler(console_handler)
        
        return logger
    
    @classmethod
    def setup_unified_logging(cls):
        """初始化统一日志系统"""
        if cls._initialized:
            return
        
        cls._config = LogConfig.from_env()
        Path(cls._config.log_directory).mkdir(exist_ok=True)
        cls._initialized = True
        
        # 清理旧的空备份文件
        cls._cleanup_empty_backups()
        
        print(f"统一日志系统初始化完成 - 目录: {cls._config.log_directory}, 级别: {logging.getLevelName(cls._config.level)}")
    
    @classmethod
    def _cleanup_empty_backups(cls):
        """清理空的时间戳备份文件"""
        log_dir = Path(cls._config.log_directory)
        if not log_dir.exists():
            return
            
        empty_files = []
        for log_file in log_dir.glob("warp_api_*.log"):
            if log_file.stat().st_size == 0:
                empty_files.append(log_file)
        
        for empty_file in empty_files:
            try:
                empty_file.unlink()
                print(f"已删除空备份文件: {empty_file.name}")
            except Exception as e:
                print(f"删除空备份文件失败 {empty_file.name}: {e}")

class SafeRotatingFileHandler(RotatingFileHandler):
    """安全的轮转文件处理器，带错误恢复"""
    
    def doRollover(self):
        """重写rollover逻辑，确保安全备份"""
        try:
            # 执行安全的文件轮转
            if self.stream:
                self.stream.close()
                self.stream = None
            
            # 安全备份当前文件
            if self.baseFilename and Path(self.baseFilename).exists():
                self._safe_backup_current_file()
            
            # 创建新的日志文件
            self.stream = self._open()
        except Exception as e:
            print(f"日志轮转失败: {e}")
            self._

# -*- coding: utf-8 -*-
"""
统一日志系统配置模块
- 解决双重日志系统冲突（warp2protobuf / protobuf2openai）
- 提供环境变量驱动的统一配置
- 提供安全的日志备份与轮转
"""

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional


# --------- 环境工具 ---------

def _env_bool(name: str, default: bool = True) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def get_log_level(env_var: str, default: str = "INFO") -> int:
    level_str = os.getenv(env_var, default).strip().upper()
    return getattr(logging, level_str, logging.INFO)


def get_formatter(format_type: str) -> logging.Formatter:
    formats = {
        "simple": "%(levelname)s - %(message)s",
        "detailed": "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        "json": '{"timestamp":"%(asctime)s","logger":"%(name)s","level":"%(levelname)s","func":"%(funcName)s","line":%(lineno)d,"msg":"%(message)s"}',
    }
    fmt = formats.get(format_type, formats["detailed"])
    return logging.Formatter(fmt)


# --------- 配置 ---------

@dataclass
class LogConfig:
    level: int = logging.INFO
    console_level: int = logging.INFO
    file_level: int = logging.DEBUG
    max_file_size: int = 10 * 1024 * 1024
    backup_count: int = 5
    format_type: str = "detailed"
    enable_rotation: bool = True
    enable_backup: bool = True
    log_directory: Path = Path("logs")

    @classmethod
    def from_env(cls) -> "LogConfig":
        return cls(
            level=get_log_level("LOG_LEVEL", os.getenv("WARP_LOG_LEVEL", "INFO")),
            console_level=get_log_level("LOG_CONSOLE_LEVEL", "INFO"),
            file_level=get_log_level("LOG_FILE_LEVEL", "DEBUG"),
            max_file_size=int(os.getenv("LOG_MAX_FILE_SIZE", "10485760")),
            backup_count=int(os.getenv("LOG_BACKUP_COUNT", "5")),
            format_type=os.getenv("LOG_FORMAT", "detailed").strip().lower(),
            enable_rotation=_env_bool("LOG_ENABLE_ROTATION", True),
            enable_backup=_env_bool("LOG_ENABLE_BACKUP", True),
            log_directory=Path(os.getenv("LOG_DIRECTORY", "logs")),
        )


# --------- 安全轮转处理器 ---------

class SafeRotatingFileHandler(RotatingFileHandler):
    """
    安全轮转：在 rollover 之前使用“复制+删除”备份当前文件，避免出现空活跃文件与丢失问题。
    """

    def doRollover(self):
        try:
            if self.stream:
                try:
                    self.stream.flush()
                except Exception:
                    pass
                try:
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None

            base_path = Path(self.baseFilename)
            if base_path.exists() and base_path.stat().st_size > 0:
                self._safe_backup_current_file(base_path)

            # 调用父类逻辑以按 backupCount 维护N个历史（即便我们已做时间戳备份，这里仍能保证文件句柄一致）
            try:
                super().doRollover()
            except Exception:
                # 某些平台上父类在我们自管备份后会报错，忽略即可。
                pass

            # 重新打开活跃文件
            self.stream = self._open()
        except Exception as e:
            print(f"[SafeRotatingFileHandler] rollover failed: {e}")
            # 降级：此处不抛出，避免应用退出

    def _safe_backup_current_file(self, base_path: Path):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = base_path.parent / f"{base_path.stem}_{ts}{base_path.suffix}"
        try:
            shutil.copy2(base_path, backup_path)
            # 清理：只删除原文件，不移动，避免句柄问题
            try:
                base_path.unlink()
            except Exception:
                # 句柄占用时可能失败，不影响后续open()
                pass
            print(f"[SafeRotatingFileHandler] backup created: {backup_path.name}")
        except Exception as e:
            print(f"[SafeRotatingFileHandler] backup failed: {e}")


# --------- 备份工具（启动备份） ---------

def safe_backup_existing_log(log_file_path: Path, max_keep: int = 10):
    """
    在启动时进行一次备份（复制+删除），避免直接移动导致的空活跃文件或写入失败。
    """
    try:
        if not log_file_path.exists():
            return
        if log_file_path.stat().st_size == 0:
            # 空文件不备份，直接跳过
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = log_file_path.parent / f"{log_file_path.stem}_{ts}{log_file_path.suffix}"
        shutil.copy2(log_file_path, backup_path)
        try:
            log_file_path.unlink()
        except Exception:
            # 句柄占用无妨
            pass

        # 清理过多的时间戳备份
        backups = sorted(
            log_file_path.parent.glob(f"{log_file_path.stem}_*{log_file_path.suffix}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[max_keep:]:
            try:
                old.unlink()
            except Exception:
                pass
        print(f"[UnifiedLogging] startup backup created: {backup_path.name}")
    except Exception as e:
        print(f"[UnifiedLogging] startup backup failed: {e}")


# --------- 日志管理器 ---------

class LoggerManager:
    """
    统一日志管理器（按 name+log_file 维度缓存），避免多次重复添加 handler。
    """
    _instances: Dict[str, logging.Logger] = {}
    _initialized: bool = False
    _config: LogConfig = LogConfig()

    @classmethod
    def setup_unified_logging(cls):
        if cls._initialized:
            return
        cls._config = LogConfig.from_env()
        try:
            cls._config.log_directory.mkdir(exist_ok=True, parents=True)
        except Exception:
            pass
        cls._initialized = True

    @classmethod
    def get_logger(cls, name: str, log_file: Optional[str] = None) -> logging.Logger:
        if not cls._initialized:
            cls.setup_unified_logging()

        cache_key = f"{name}:{log_file or '-'}"
        if cache_key in cls._instances:
            return cls._instances[cache_key]

        logger = logging.getLogger(name)
        logger.setLevel(cls._config.level)

        # 清理已有 handlers，避免重复输出
        for h in logger.handlers[:]:
            try:
                logger.removeHandler(h)
            except Exception:
                pass

        # 文件 handler
        if log_file:
            file_path = cls._config.log_directory / log_file
            if cls._config.enable_backup:
                safe_backup_existing_log(file_path, max_keep=max(cls._config.backup_count, 5))

            if cls._config.enable_rotation:
                fh = SafeRotatingFileHandler(
                    file_path,
                    maxBytes=cls._config.max_file_size,
                    backupCount=cls._config.backup_count,
                    encoding="utf-8",
                )
            else:
                fh = logging.FileHandler(file_path, encoding="utf-8")

            fh.setLevel(cls._config.file_level)
            fh.setFormatter(get_formatter(cls._config.format_type))
            logger.addHandler(fh)

        # 控制台 handler
        ch = logging.StreamHandler()
        ch.setLevel(cls._config.console_level)
        ch.setFormatter(get_formatter(cls._config.format_type))
        logger.addHandler(ch)

        cls._instances[cache_key] = logger
        return logger
