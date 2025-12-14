import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def get_env_variable(key: str, default: Optional[str] = None) -> str:
    """
    获取环境变量，如果不存在则返回默认值
    
    Args:
        key: 环境变量键
        default: 默认值
        
    Returns:
        环境变量值或默认值
    """
    value = os.getenv(key, default)
    if value is None:
        logger.warning(f"环境变量 {key} 未设置")
    return value

def validate_image_urls(image_urls: list) -> list:
    """
    验证图片URL列表
    
    Args:
        image_urls: 图片URL列表
        
    Returns:
        有效的图片URL列表
    """
    valid_urls = []
    for url in image_urls:
        if isinstance(url, str) and url.startswith(('http://', 'https://')):
            valid_urls.append(url)
        else:
            logger.warning(f"无效的图片URL: {url}")
    
    return valid_urls

def sanitize_content(content: str, max_length: int = 2000) -> str:
    """
    清理内容，限制长度并移除不安全字符
    
    Args:
        content: 原始内容
        max_length: 最大长度限制
        
    Returns:
        清理后的内容
    """
    # 移除HTML标签
    import re
    content = re.sub(r'<[^>]+>', '', content)
    
    # 限制长度
    if len(content) > max_length:
        content = content[:max_length] + "..."
        logger.info(f"内容被截断至 {max_length} 字符")
    
    return content

def format_response(success: bool, message: str, data: dict = None) -> dict:
    """
    格式化API响应
    
    Args:
        success: 是否成功
        message: 消息
        data: 数据
        
    Returns:
        格式化的响应字典
    """
    response = {
        "success": success,
        "message": message
    }
    
    if data is not None:
        response["data"] = data
    
    return response