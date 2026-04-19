import os
import sys
from loguru import logger
from datetime import datetime

def setup_logger():
    """配置全局日志系统，复刻主项目规范"""
    # 获取脚本所在目录，确保 logs 文件夹在 scripts 目录下
    scripts_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(scripts_dir, "logs")
    
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 构造日志路径：dailybot_flow_YYYY-MM-DD.log
    log_path = os.path.join(log_dir, "dailybot_flow_{time:YYYY-MM-DD}.log")

    # 1. 移除默认配置
    logger.remove()

    # 2. 添加控制台输出 (保持当前打印风格不要变)
    # 使用自定义格式，去除时间戳等干扰，仅保留消息本身，确保仪表盘和边框不乱码
    logger.add(
        sys.stdout,
        level="INFO",
        format="<level>{message}</level>", 
        colorize=True
    )

    # 3. 添加文件输出 (工业级详细记录)
    logger.add(
        log_path,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} - {message}",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        enqueue=True # 异步写入，不影响主流程性能
    )

    return logger

# 初始化并导出单例
log = setup_logger()
