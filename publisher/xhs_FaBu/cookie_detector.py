#!/usr/bin/env python3
"""
简化的Cookie检测器 - 仅支持MCP共享浏览器
"""

import os
import sqlite3
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class CookieDetector:
    """简化的Cookie检测器 - 仅检测MCP共享浏览器"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.user_data_dir = self.project_root / "user_data"
        
    def _get_mcp_shared_browser_configs(self) -> List[Dict]:
        """获取MCP共享浏览器配置"""
        configs = []
        
        if not self.user_data_dir.exists():
            logger.warning(f"用户数据目录不存在: {self.user_data_dir}")
            return configs
            
        # 遍历user_data目录下的所有子目录
        for subdir in self.user_data_dir.iterdir():
            if subdir.is_dir():
                # 检查是否存在Cookie文件
                cookie_path = subdir / "Default" / "Network" / "Cookies"
                if cookie_path.exists():
                    config = {
                        "name": f"MCP_Shared_{subdir.name}",
                        "user_data_dir": str(subdir),
                        "profiles": [{"name": "Default", "path": "Default"}],
                        "is_mcp_shared": True
                    }
                    configs.append(config)
                    logger.info(f"发现MCP共享浏览器: {subdir.name}")
        
        return configs
    
    def _get_browser_cookie_path(self, browser_config: Dict, profile: Dict) -> Optional[str]:
        """获取浏览器Cookie文件路径"""
        try:
            if browser_config.get("is_mcp_shared"):
                # MCP共享浏览器路径
                user_data_dir = browser_config["user_data_dir"]
                cookie_path = Path(user_data_dir) / "Default" / "Network" / "Cookies"
                return str(cookie_path) if cookie_path.exists() else None
            
            return None
            
        except Exception as e:
            logger.error(f"获取Cookie路径失败: {e}")
            return None
    
    def _read_cookies_from_db(self, db_path: str) -> List[Dict]:
        """从SQLite数据库读取Cookie"""
        cookies = []
        temp_db_path = None
        
        try:
            # 创建临时副本以避免数据库锁定
            with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as temp_file:
                temp_db_path = temp_file.name
                shutil.copy2(db_path, temp_db_path)
            
            # 连接到临时数据库
            conn = sqlite3.connect(temp_db_path)
            cursor = conn.cursor()
            
            # 查询小红书相关的Cookie
            query = """
            SELECT name, value, host_key, path, expires_utc, is_secure, is_httponly
            FROM cookies 
            WHERE host_key LIKE '%xiaohongshu%' OR host_key LIKE '%xhscdn%' OR host_key LIKE '%xhs%'
            """
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            for row in rows:
                cookie = {
                    'name': row[0],
                    'value': row[1],
                    'domain': row[2],
                    'path': row[3],
                    'expires': row[4],
                    'secure': bool(row[5]),
                    'httponly': bool(row[6])
                }
                cookies.append(cookie)
            
            conn.close()
            
        except Exception as e:
            logger.error(f"读取Cookie数据库失败 {db_path}: {e}")
        finally:
            # 清理临时文件
            if temp_db_path and os.path.exists(temp_db_path):
                try:
                    os.unlink(temp_db_path)
                except:
                    pass
        
        return cookies
    
    def _calculate_login_score(self, cookies: List[Dict]) -> int:
        """计算登录分数"""
        score = 0
        
        # 重要Cookie名称及其权重
        important_cookies = {
            'a1': 15,           # 用户认证token
            'webId': 10,        # 用户ID
            'web_session': 8,   # 会话token
            'userId': 8,        # 用户ID
            'sessionId': 5,     # 会话ID
            'acw_tc': 3,        # 反爬虫token
            'abRequestId': 2,   # 请求ID
        }
        
        for cookie in cookies:
            cookie_name = cookie.get('name', '')
            if cookie_name in important_cookies:
                score += important_cookies[cookie_name]
        
        return score
    
    def detect_xiaohongshu_login_status(self, user_id: str = None) -> Dict:
        """检测小红书登录状态"""
        try:
            # 获取MCP共享浏览器配置
            browser_configs = self._get_mcp_shared_browser_configs()
            
            if not browser_configs:
                return {
                    "logged_in": False,
                    "confidence": "very_low",
                    "message": "未找到MCP共享浏览器",
                    "browsers_detected": 0,
                    "total_cookies": 0,
                    "login_score": 0
                }
            
            all_cookies = []
            browser_results = []
            
            # 遍历所有浏览器配置
            for browser_config in browser_configs:
                browser_name = browser_config["name"]
                
                for profile in browser_config["profiles"]:
                    cookie_path = self._get_browser_cookie_path(browser_config, profile)
                    
                    if cookie_path and os.path.exists(cookie_path):
                        cookies = self._read_cookies_from_db(cookie_path)
                        login_score = self._calculate_login_score(cookies)
                        
                        browser_result = {
                            "browser": browser_name,
                            "profile": profile["name"],
                            "cookies_count": len(cookies),
                            "login_score": login_score,
                            "cookie_path": cookie_path
                        }
                        browser_results.append(browser_result)
                        all_cookies.extend(cookies)
            
            # 分析总体登录状态
            total_cookies = len(all_cookies)
            total_score = sum(result["login_score"] for result in browser_results)
            
            # 检查关键登录指标
            session_cookies = [c for c in all_cookies if any(key in c['name'].lower() for key in ['session', 'token', 'auth'])]
            user_cookies = [c for c in all_cookies if any(key in c['name'].lower() for key in ['user', 'uid', 'id'])]
            auth_cookies = [c for c in all_cookies if c['name'] in ['a1', 'webId', 'web_session']]
            
            # 判断登录状态和置信度
            if total_score >= 20 and len(auth_cookies) >= 2:
                logged_in = True
                confidence = "high"
            elif total_score >= 10 and len(auth_cookies) >= 1:
                logged_in = True
                confidence = "medium"
            elif total_score >= 5:
                logged_in = True
                confidence = "low"
            else:
                logged_in = False
                confidence = "very_low"
            
            return {
                "logged_in": logged_in,
                "confidence": confidence,
                "message": f"检测到 {len(browser_configs)} 个MCP共享浏览器，总登录分数: {total_score}",
                "browsers_detected": len(browser_configs),
                "browser_results": browser_results,
                "total_cookies": total_cookies,
                "login_score": total_score,
                "login_indicators": {
                    "session_cookies": len(session_cookies),
                    "user_cookies": len(user_cookies),
                    "auth_cookies": len(auth_cookies)
                }
            }
            
        except Exception as e:
            logger.error(f"检测登录状态失败: {e}")
            return {
                "logged_in": False,
                "confidence": "very_low",
                "message": f"检测失败: {str(e)}",
                "browsers_detected": 0,
                "total_cookies": 0,
                "login_score": 0
            }