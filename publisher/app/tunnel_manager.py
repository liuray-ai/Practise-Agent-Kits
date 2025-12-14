#!/usr/bin/env python3
"""
Cloudflared隧道管理器
自动获取隧道URL并更新openapi.yaml配置
"""

import os
import re
import time
import yaml
import requests
import logging
import subprocess
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class TunnelManager:
    """Cloudflared隧道管理器"""
    
    def __init__(self, openapi_file: str = "openapi.yaml"):
        self.openapi_file = openapi_file
        self.tunnel_url = None
        self.cloudflared_proc: Optional[subprocess.Popen] = None
        self.metrics_endpoint = "http://127.0.0.1:20242/metrics"

    # ================= 隧道启动与检测 =================

    def is_cloudflared_running(self) -> bool:
        """判断 cloudflared 是否在运行（通过 metrics 或进程名）"""
        # 先尝试 metrics
        try:
            resp = requests.get(self.metrics_endpoint, timeout=3)
            if resp.status_code == 200:
                return True
        except Exception:
            pass

        # 再查进程（Windows 环境）
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and "cloudflared.exe" in result.stdout
        except Exception:
            return False

    def start_cloudflared_quick_tunnel(self, local_port: int = 5001) -> bool:
        """启动 cloudflared 快速隧道，将本地服务暴露到公网"""
        try:
            exe_path = os.path.join(os.getcwd(), "cloudflared.exe")
            if not os.path.exists(exe_path):
                logger.error("❌ 未找到 cloudflared.exe，请确保其位于项目根目录")
                return False

            # 使用 HTTP/2 协议以提升稳定性，启用本地 metrics，写日志到文件
            args = [
                exe_path,
                "tunnel",
                "--url", f"http://127.0.0.1:{local_port}",
                "--protocol", "http2",
                "--metrics", "127.0.0.1:20242",
                "--no-autoupdate",
                "--loglevel", "info",
                "--logfile", os.path.join(os.getcwd(), "cloudflared.log")
            ]

            # 以非阻塞方式启动，保留进程句柄
            self.cloudflared_proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            logger.info("🚀 已启动 Cloudflared 快速隧道进程（HTTP/2 模式）")
            return True
        except Exception as e:
            logger.error(f"❌ 启动 cloudflared 失败: {e}")
            return False
        
    def get_tunnel_url_from_metrics(self) -> Optional[str]:
        """从cloudflared metrics API获取隧道URL"""
        try:
            # cloudflared默认在127.0.0.1:20242提供metrics
            response = requests.get(self.metrics_endpoint, timeout=5)
            if response.status_code == 200:
                metrics_text = response.text
                # 查找隧道URL的模式
                url_pattern = r'cloudflared_tunnel_user_hostnames_counts{userHostname="([^"]+)"}'
                matches = re.findall(url_pattern, metrics_text)
                if matches:
                    hostname = matches[0]
                    # 确保不重复添加https://
                    if hostname.startswith('http://') or hostname.startswith('https://'):
                        return hostname
                    else:
                        return f"https://{hostname}"
        except Exception as e:
            logger.debug(f"无法从metrics获取隧道URL: {e}")
        return None
    
    def get_tunnel_url_from_process(self) -> Optional[str]:
        """通过检查cloudflared进程输出获取隧道URL"""
        try:
            # 使用netstat查找cloudflared进程
            result = subprocess.run(
                ["netstat", "-ano"], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if ":20242" in line and "LISTENING" in line:
                        # 找到了metrics端口，说明cloudflared在运行
                        return self.get_tunnel_url_from_metrics()
        except Exception as e:
            logger.debug(f"无法通过进程检查获取隧道URL: {e}")
        return None
    
    def wait_for_tunnel_url(self, max_wait_time: int = 30) -> Optional[str]:
        """等待隧道URL可用"""
        logger.info("等待cloudflared隧道启动...")
        
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            # 首先尝试从metrics获取
            url = self.get_tunnel_url_from_metrics()
            if url:
                logger.info(f"✅ 成功获取隧道URL: {url}")
                self.tunnel_url = url
                return url
            
            # 如果metrics不可用，尝试其他方法
            url = self.get_tunnel_url_from_process()
            if url:
                logger.info(f"✅ 成功获取隧道URL: {url}")
                self.tunnel_url = url
                return url

            # 尝试从日志文件提取
            log_url = self.get_tunnel_url_from_log()
            if log_url:
                logger.info(f"✅ 从日志获取隧道URL: {log_url}")
                self.tunnel_url = log_url
                return log_url
            
            time.sleep(2)
        
        logger.warning(f"⚠️ 在{max_wait_time}秒内未能获取到隧道URL")
        return None

    def get_tunnel_url_from_log(self) -> Optional[str]:
        """从 cloudflared.log 文件中提取生成的 quick tunnel 域名"""
        try:
            log_path = os.path.join(os.getcwd(), "cloudflared.log")
            if not os.path.exists(log_path):
                return None
            # 读取最近的内容
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()[-10000:]  # 取最后10KB，避免文件过大
            # 匹配 https://xxxx.trycloudflare.com
            m = re.findall(r"https://[a-z0-9\-]+\.trycloudflare\.com", content, flags=re.IGNORECASE)
            if m:
                return m[-1]
        except Exception as e:
            logger.debug(f"从日志提取隧道URL失败: {e}")
        return None

    def ensure_tunnel_running_and_update_openapi(self, local_port: int = 5001, max_wait_time: int = 30) -> Optional[str]:
        """确保隧道运行，自动更新 openapi.yaml，并返回当前隧道 URL"""
        # 如果 cloudflared 未运行，则启动
        if not self.is_cloudflared_running():
            logger.info("🔧 未检测到 Cloudflared 运行，尝试启动快速隧道...")
            started = self.start_cloudflared_quick_tunnel(local_port)
            if not started:
                logger.warning("⚠️ 启动快速隧道失败，无法自动更新 OpenAPI URL")
                return None

        # 等待 URL 可用
        url = self.wait_for_tunnel_url(max_wait_time=max_wait_time)
        if not url:
            logger.warning("⚠️ 隧道未能在预期时间内就绪")
            return None

        # 与 openapi.yaml 比较并更新
        current_openapi_url = self.get_current_openapi_url()
        if current_openapi_url != url:
            logger.info("🔄 检测到隧道 URL 更新，准备写入 openapi.yaml")
            if self.update_openapi_yaml(url):
                logger.info("✅ OpenAPI URL 已自动更新")
            else:
                logger.error("❌ 写入 openapi.yaml 失败")
                return None
        else:
            logger.info("✅ OpenAPI URL 已是最新，无需更新")

        self.tunnel_url = url
        return url
    
    def create_default_openapi_yaml(self, base_url: str = "http://127.0.0.1:5001") -> bool:
        """创建默认的openapi.yaml文件"""
        try:
            default_openapi = {
                'openapi': '3.0.0',
                'info': {
                    'title': '小红书MCP发布器',
                    'description': '用于自动发布内容到小红书平台的MCP插件，支持图文发布、登录状态检测等功能',
                    'version': '1.0.0',
                    'contact': {
                        'name': '小红书MCP发布器',
                        'url': 'https://github.com/your-repo/redbook_mcp'
                    }
                },
                'servers': [
                    {
                        'url': base_url,
                        'description': '本地开发服务器'
                    }
                ],
                'paths': {
                    '/api/health': {
                        'get': {
                            'summary': '健康检查',
                            'description': '检查服务是否正常运行',
                            'operationId': 'healthCheck',
                            'responses': {
                                '200': {
                                    'description': '服务正常',
                                    'content': {
                                        'application/json': {
                                            'schema': {
                                                'type': 'object',
                                                'properties': {
                                                    'code': {'type': 'integer', 'example': 0},
                                                    'msg': {'type': 'string', 'example': 'success'},
                                                    'data': {
                                                        'type': 'object',
                                                        'properties': {
                                                            'status': {'type': 'string', 'example': 'healthy'},
                                                            'service': {'type': 'string', 'example': '小红书MCP发布器'},
                                                            'version': {'type': 'string', 'example': '1.0.0'}
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    '/api/detect-login': {
                        'get': {
                            'summary': '检测登录状态',
                            'description': '检测指定用户在小红书平台的登录状态',
                            'operationId': 'detectLogin',
                            'parameters': [
                                {
                                    'name': 'user_id',
                                    'in': 'query',
                                    'description': '用户ID，默认为default',
                                    'required': False,
                                    'schema': {'type': 'string', 'default': 'default'}
                                }
                            ],
                            'responses': {
                                '200': {
                                    'description': '检测成功',
                                    'content': {
                                        'application/json': {
                                            'schema': {
                                                'type': 'object',
                                                'properties': {
                                                    'code': {'type': 'integer', 'example': 0},
                                                    'msg': {'type': 'string', 'example': 'success'},
                                                    'data': {
                                                        'type': 'object',
                                                        'properties': {
                                                            'success': {'type': 'boolean', 'example': True},
                                                            'logged_in': {'type': 'boolean', 'example': True},
                                                            'confidence': {'type': 'string', 'example': 'high'},
                                                            'message': {'type': 'string', 'example': '检测完成'}
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    '/api/publish': {
                        'post': {
                            'summary': '发布小红书笔记',
                            'description': '发布图文内容到小红书平台',
                            'operationId': 'publishNote',
                            'requestBody': {
                                'required': True,
                                'content': {
                                    'application/json': {
                                        'schema': {
                                            'type': 'object',
                                            'required': ['content'],
                                            'properties': {
                                                'user_id': {'type': 'string', 'description': '用户ID', 'default': 'default'},
                                                'content': {'type': 'string', 'description': '笔记内容', 'example': '这是一篇测试笔记的内容'},
                                                'title': {'type': 'string', 'description': '笔记标题', 'example': '测试笔记标题'},
                                                'images': {'type': 'array', 'description': '图片URL列表', 'items': {'type': 'string'}},
                                                'dry_run': {'type': 'boolean', 'description': '是否为测试模式（不实际发布）', 'default': False}
                                            }
                                        }
                                    }
                                }
                            },
                            'responses': {
                                '200': {
                                    'description': '发布成功',
                                    'content': {
                                        'application/json': {
                                            'schema': {
                                                'type': 'object',
                                                'properties': {
                                                    'code': {'type': 'integer', 'example': 0},
                                                    'msg': {'type': 'string', 'example': 'success'},
                                                    'data': {
                                                        'type': 'object',
                                                        'properties': {
                                                            'success': {'type': 'boolean', 'example': True},
                                                            'message': {'type': 'string', 'example': '发布成功'}
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    '/api/preview': {
                        'post': {
                            'summary': '预览发布内容',
                            'description': '预览即将发布的内容，不实际发布',
                            'operationId': 'previewNote',
                            'requestBody': {
                                'required': True,
                                'content': {
                                    'application/json': {
                                        'schema': {
                                            'type': 'object',
                                            'properties': {
                                                'content': {'type': 'string', 'description': '笔记内容'},
                                                'title': {'type': 'string', 'description': '笔记标题'},
                                                'images': {'type': 'array', 'description': '图片URL列表', 'items': {'type': 'string'}}
                                            }
                                        }
                                    }
                                }
                            },
                            'responses': {
                                '200': {
                                    'description': '预览成功',
                                    'content': {
                                        'application/json': {
                                            'schema': {
                                                'type': 'object',
                                                'properties': {
                                                    'code': {'type': 'integer', 'example': 0},
                                                    'msg': {'type': 'string', 'example': 'success'},
                                                    'data': {
                                                        'type': 'object',
                                                        'properties': {
                                                            'success': {'type': 'boolean', 'example': True},
                                                            'message': {'type': 'string', 'example': '预览生成成功'}
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            # 写入文件
            with open(self.openapi_file, 'w', encoding='utf-8') as f:
                yaml.dump(default_openapi, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            
            logger.info(f"✅ 已创建默认的openapi.yaml文件: {base_url}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 创建默认openapi.yaml失败: {e}")
            return False

    def update_openapi_yaml(self, new_url: str) -> bool:
        """更新openapi.yaml中的服务器URL，如果文件不存在则创建"""
        try:
            # 如果文件不存在，先创建默认文件
            if not os.path.exists(self.openapi_file):
                logger.info("📄 openapi.yaml文件不存在，正在创建默认文件...")
                if not self.create_default_openapi_yaml(new_url):
                    return False
                return True
            
            # 读取现有的openapi.yaml
            with open(self.openapi_file, 'r', encoding='utf-8') as f:
                openapi_data = yaml.safe_load(f)
            
            # 更新服务器URL
            if 'servers' not in openapi_data:
                openapi_data['servers'] = []
            
            if len(openapi_data['servers']) == 0:
                openapi_data['servers'].append({})
            
            # 更新第一个服务器的URL
            openapi_data['servers'][0]['url'] = new_url
            openapi_data['servers'][0]['description'] = "Cloudflare Tunnel 公网地址"
            
            # 写回文件
            with open(self.openapi_file, 'w', encoding='utf-8') as f:
                yaml.dump(openapi_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            
            logger.info(f"✅ 已更新openapi.yaml中的服务器URL: {new_url}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 更新openapi.yaml失败: {e}")
            return False
    
    def get_current_openapi_url(self) -> Optional[str]:
        """获取当前openapi.yaml中配置的URL"""
        try:
            with open(self.openapi_file, 'r', encoding='utf-8') as f:
                openapi_data = yaml.safe_load(f)
            
            if 'servers' in openapi_data and len(openapi_data['servers']) > 0:
                return openapi_data['servers'][0].get('url')
        except Exception as e:
            logger.debug(f"读取openapi.yaml失败: {e}")
        return None
    
    def auto_update_if_needed(self) -> Optional[str]:
        """如果需要，自动更新隧道URL"""
        # 获取当前隧道URL
        current_tunnel_url = self.wait_for_tunnel_url(max_wait_time=10)
        if not current_tunnel_url:
            logger.warning("⚠️ 无法获取当前隧道URL")
            return None
        
        # 获取openapi.yaml中的当前URL
        current_openapi_url = self.get_current_openapi_url()
        
        # 如果URL不同，则更新
        if current_tunnel_url != current_openapi_url:
            logger.info(f"🔄 检测到URL变化:")
            logger.info(f"   当前隧道: {current_tunnel_url}")
            logger.info(f"   配置文件: {current_openapi_url}")
            
            if self.update_openapi_yaml(current_tunnel_url):
                logger.info("✅ 自动更新完成")
                return current_tunnel_url
            else:
                logger.error("❌ 自动更新失败")
                return None
        else:
            logger.info("✅ URL无需更新，配置已是最新")
            return current_tunnel_url