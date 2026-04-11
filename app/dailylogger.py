import asyncio
import logging
import os
from logging.handlers import TimedRotatingFileHandler

# 获取项目根目录（当前文件位于 app/ 目录下）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG_DIR = os.path.join(BASE_DIR, "logs")


class QueueLogHandler(logging.Handler):
    """
    Custom handler to push logs to an asyncio queue for streaming.
    """

    def __init__(self, log_queue: asyncio.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            # Create a non-blocking put if loop is running, else ignore
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    # Use loop.create_task to put in queue to avoid blocking sync logging
                    # But queue.put_nowait is safer for sync emit if queue is unbounded
                    self.log_queue.put_nowait(msg)
            except (RuntimeError, asyncio.QueueFull):
                pass
        except Exception:
            self.handleError(record)


# 全局的日志队列，确保所有按模块生成的 Logger 都可以把日志推送到同一个 SSE 前端输出流
global_log_queue = asyncio.Queue()


# 全局共享 Handlers，防止多个 Logger 实例往同一个文件写入和切割时发生冲突
_shared_file_handler = None
_shared_console_handler = None
_shared_queue_handler = None

def _get_shared_handlers(target_dir: str):
    global _shared_file_handler, _shared_console_handler, _shared_queue_handler
    
    if _shared_console_handler is None:
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
        )
        
        # 1. 物理文件 Handler (按天拆分，所有模块共用 TTAiTradingSystem.log)
        log_filename = os.path.join(target_dir, "sd_video.log")
        _shared_file_handler = TimedRotatingFileHandler(
            log_filename, when='midnight', interval=1, backupCount=0, encoding='utf-8'
        )
        _shared_file_handler.suffix = "%Y-%m-%d.log"
        file_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(name)s] - [%(filename)s:%(lineno)d:%(funcName)s] - %(message)s'
        )
        _shared_file_handler.setFormatter(file_formatter)
        
        # 2. 控制台 Console Handler
        _shared_console_handler = logging.StreamHandler()
        _shared_console_handler.setFormatter(console_formatter)
        
        # 3. 前端流式响应 SSE Handler
        _shared_queue_handler = QueueLogHandler(global_log_queue)
        _shared_queue_handler.setFormatter(console_formatter)
        
    return _shared_file_handler, _shared_console_handler, _shared_queue_handler


def get_logger(name: str = "daily_logger", log_dir: str = None) -> logging.Logger:
    """
    获取日志记录器的工厂函数。
    所有模块共用一个 system.log 文件，通过日志内的 [name] 区分模块来源。
    """
    logger = logging.getLogger(name)

    # 避免重复添加 Handler
    if len(logger.handlers) > 0:
        return logger

    logger.setLevel(logging.DEBUG)

    target_dir = log_dir or DEFAULT_LOG_DIR
    os.makedirs(target_dir, exist_ok=True)

    file_h, console_h, queue_h = _get_shared_handlers(target_dir)

    logger.addHandler(file_h)
    logger.addHandler(console_h)
    logger.addHandler(queue_h)
    
    # 防止向 root logger 传递导致的控制台多重打印现象
    logger.propagate = False

    return logger


class DailyLogger:
    """
    为了向后兼容旧项目中的对象导入方式，保留此类。
    """

    def __init__(self, log_directory='logs', logger_name='daily_logger'):
        # 兼容旧代码使用相对路径 'logs' 的情况，使用绝对路径确保日志不乱飞
        if log_directory == 'logs':
            self.log_directory = DEFAULT_LOG_DIR
        else:
            self.log_directory = log_directory
            
        self.logger_name = logger_name
        self.logger = get_logger(self.logger_name, self.log_directory)
        self.log_queue = global_log_queue

    def get_logger(self):
        """获取日志记录器实例"""
        return self.logger

    def get_log_queue(self):
        return self.log_queue


# 初始化全局默认实例，保持与旧业务代码兼容
daily_logger = DailyLogger()
logger = daily_logger.get_logger()
log_queue = daily_logger.get_log_queue()
