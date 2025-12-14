#!/usr/bin/env python3
"""
小红书MCP共享浏览器发布器
专门用于在MCP共享浏览器中发布内容
"""

import os
import time
import asyncio
import logging
import random
import uuid
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import requests
from urllib.parse import urlparse
import re

try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext, Locator
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("警告: Playwright 未安装，请运行: pip install playwright && playwright install")

logger = logging.getLogger(__name__)

class HumanBehaviorSimulator:
    """真人行为模拟器"""
    
    @staticmethod
    def thinking_delay() -> float:
        """思考延迟：模拟用户思考时间"""
        return random.uniform(0.1, 0.4)  # 大幅减少思考时间
    
    @staticmethod
    def reading_delay(text_length: int = 0) -> float:
        """阅读延迟：根据文本长度模拟阅读时间"""
        base_time = random.uniform(0.1, 0.3)  # 大幅减少基础阅读时间
        reading_time = text_length * random.uniform(0.005, 0.01) if text_length > 0 else 0  # 大幅减少每字符阅读时间
        return base_time + reading_time
    
    @staticmethod
    def hesitation_delay() -> float:
        """犹豫延迟：模拟用户犹豫不决"""
        return random.uniform(2.0, 5.0)
    
    @staticmethod
    def mouse_move_delay() -> float:
        """鼠标移动延迟"""
        return random.uniform(0.3, 0.8)
    
    @staticmethod
    def click_delay() -> float:
        """点击后延迟"""
        return random.uniform(1.2, 2.5)
    
    @staticmethod
    def typing_delay() -> float:
        """打字间隔延迟"""
        return random.uniform(0.08, 0.25)
    
    @staticmethod
    def page_load_delay() -> float:
        """页面加载等待延迟"""
        return random.uniform(2.0, 4.0)
    
    @staticmethod
    def button_sequence_delay() -> float:
        """按钮序列操作间隔"""
        return random.uniform(2.5, 5.0)
    
    @staticmethod
    def random_pause() -> bool:
        """随机暂停判断（20%概率）"""
        return random.random() < 0.2
    
    @staticmethod
    def distraction_delay() -> float:
        """分心延迟：模拟用户被其他事情分心"""
        return random.uniform(1.0, 3.0)  # 减少分心时长
    
    @staticmethod
    def generate_human_click_coordinates(box: Dict[str, float]) -> Tuple[float, float]:
        """
        生成更真实的点击坐标
        模拟人类点击习惯：
        1. 避免边缘点击
        2. 偏向中心区域但有随机性
        3. 使用正态分布而非均匀分布
        """
        width = box['width']
        height = box['height']
        
        # 计算安全边距（避免点击到边缘）
        margin_x = max(8, width * 0.15)
        margin_y = max(5, height * 0.15)
        
        # 可点击区域
        clickable_width = width - 2 * margin_x
        clickable_height = height - 2 * margin_y
        
        # 使用正态分布，偏向中心但有随机性
        # 标准差设为可点击区域的1/4，这样大部分点击会在中心附近
        center_offset_x = random.gauss(0, clickable_width / 4)
        center_offset_y = random.gauss(0, clickable_height / 4)
        
        # 限制在可点击区域内
        center_offset_x = max(-clickable_width/2, min(clickable_width/2, center_offset_x))
        center_offset_y = max(-clickable_height/2, min(clickable_height/2, center_offset_y))
        
        # 计算最终坐标
        x = box['x'] + margin_x + clickable_width/2 + center_offset_x
        y = box['y'] + margin_y + clickable_height/2 + center_offset_y
        
        return x, y
    
    @staticmethod
    def generate_mouse_path(start_x: float, start_y: float, end_x: float, end_y: float) -> List[Tuple[float, float]]:
        """
        生成更真实的鼠标移动路径
        模拟人类鼠标移动：不是直线，而是略微弯曲的路径
        """
        # 计算距离
        distance = ((end_x - start_x) ** 2 + (end_y - start_y) ** 2) ** 0.5
        
        # 根据距离决定路径点数量
        num_points = max(3, min(8, int(distance / 50)))
        
        path = [(start_x, start_y)]
        
        for i in range(1, num_points):
            # 线性插值
            t = i / num_points
            linear_x = start_x + (end_x - start_x) * t
            linear_y = start_y + (end_y - start_y) * t
            
            # 添加随机偏移，模拟人类不完美的鼠标移动
            offset_range = min(20, distance * 0.1)
            offset_x = random.uniform(-offset_range, offset_range)
            offset_y = random.uniform(-offset_range, offset_range)
            
            path.append((linear_x + offset_x, linear_y + offset_y))
        
        path.append((end_x, end_y))
        return path
    
    @staticmethod
    def get_typing_pattern(text_length: int) -> dict:
        """
        根据文本长度生成打字模式
        """
        if text_length <= 10:
            return {
                'base_delay': (5, 15),  # 短文本，非常快
                'pause_probability': 0.05,
                'pause_delay': (0.02, 0.08),
                'thinking_interval': 12,
                'thinking_delay': (0.05, 0.15)
            }
        elif text_length <= 50:
            return {
                'base_delay': (8, 20),  # 中等文本，快速
                'pause_probability': 0.08,
                'pause_delay': (0.05, 0.12),
                'thinking_interval': 20,
                'thinking_delay': (0.08, 0.2)
            }
        else:
            return {
                'base_delay': (10, 25),  # 长文本，流畅快速
                'pause_probability': 0.1,
                'pause_delay': (0.08, 0.2),
                'thinking_interval': 30,
                'thinking_delay': (0.1, 0.3)
            }
    
    @staticmethod
    def simulate_typing_errors(text: str, error_rate: float = 0.02) -> List[dict]:
        """
        模拟打字错误和修正
        """
        actions = []
        
        for i, char in enumerate(text):
            # 正常输入字符
            actions.append({'type': 'type', 'char': char})
            
            # 随机打字错误
            if random.random() < error_rate:
                # 输入错误字符
                wrong_char = random.choice('abcdefghijklmnopqrstuvwxyz')
                actions.append({'type': 'type', 'char': wrong_char})
                
                # 暂停（发现错误）
                actions.append({'type': 'pause', 'duration': random.uniform(0.2, 0.5)})
                
                # 删除错误字符
                actions.append({'type': 'backspace'})
                
                # 再次暂停（重新思考）
                actions.append({'type': 'pause', 'duration': random.uniform(0.1, 0.3)})
        
        return actions

class RealXHSPublisher:
    """小红书MCP共享浏览器发布器"""
    
    def __init__(self, user_id: str = "default", headless: bool = False, auto_close: bool = False, use_system_profile: bool = False):
        self.user_id = user_id
        self.headless = headless
        self.auto_close = auto_close
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        
        # 使用MCP共享浏览器用户数据目录
        self.user_data_dir = Path(f"user_data/{user_id}")
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"使用MCP共享浏览器用户数据目录: {self.user_data_dir}")
        
        # 下载目录
        self.download_dir = Path(f"downloads/{user_id}")
        self.download_dir.mkdir(parents=True, exist_ok=True)
    
    async def random_click(self, selector: str, timeout: int = 30000, retry_count: int = 3) -> bool:
        """
        随机坐标点击元素，模拟真实用户行为
        """
        for attempt in range(retry_count):
            try:
                # 等待元素出现
                element = await self.page.wait_for_selector(selector, timeout=timeout)
                if not element:
                    logger.warning(f"元素未找到: {selector}")
                    continue
                
                # 检查元素是否被遮挡
                if await self._is_element_blocked(element):
                    logger.info(f"元素被遮挡，尝试处理遮挡: {selector}")
                    await self._handle_element_blocking()
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                    continue
                
                # 获取元素边界框
                box = await element.bounding_box()
                if not box:
                    logger.warning(f"无法获取元素边界框: {selector}")
                    continue
                
                # 使用智能坐标生成（模拟真人点击习惯）
                x, y = HumanBehaviorSimulator.generate_human_click_coordinates(box)
                
                # 获取当前鼠标位置（如果可能）
                current_mouse = await self.page.evaluate("() => ({ x: 0, y: 0 })")  # 简化处理
                
                # 生成真实的鼠标移动路径
                mouse_path = HumanBehaviorSimulator.generate_mouse_path(
                    current_mouse.get('x', 0), current_mouse.get('y', 0), x, y
                )
                
                # 沿路径移动鼠标
                for path_x, path_y in mouse_path[:-1]:
                    await self.page.mouse.move(path_x, path_y)
                    await asyncio.sleep(random.uniform(0.02, 0.08))  # 路径点之间的小延迟
                
                # 最终移动到目标位置
                await self.page.mouse.move(x, y)
                await asyncio.sleep(HumanBehaviorSimulator.mouse_move_delay())
                
                # 随机暂停（模拟用户犹豫）
                if HumanBehaviorSimulator.random_pause():
                    await asyncio.sleep(HumanBehaviorSimulator.hesitation_delay())
                
                # 随机坐标点击
                await self.page.mouse.click(x, y)
                logger.info(f"随机坐标点击成功: {selector} at ({x:.1f}, {y:.1f})")
                
                # 点击后等待（模拟真人反应时间）
                await asyncio.sleep(HumanBehaviorSimulator.click_delay())
                return True
                
            except Exception as e:
                logger.warning(f"随机点击失败 (尝试 {attempt + 1}/{retry_count}): {selector} - {e}")
                if attempt < retry_count - 1:
                    await asyncio.sleep(random.uniform(1, 2))
                
        return False
    
    async def _is_element_blocked(self, element) -> bool:
        """
        增强的元素遮挡检测
        检测多个点位，确保元素真正可点击
        """
        try:
            box = await element.bounding_box()
            if not box:
                return True
            
            # 检测多个点位：中心、四个角的内侧点
            test_points = [
                (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2),  # 中心
                (box['x'] + box['width'] * 0.25, box['y'] + box['height'] * 0.25),  # 左上
                (box['x'] + box['width'] * 0.75, box['y'] + box['height'] * 0.25),  # 右上
                (box['x'] + box['width'] * 0.25, box['y'] + box['height'] * 0.75),  # 左下
                (box['x'] + box['width'] * 0.75, box['y'] + box['height'] * 0.75),  # 右下
            ]
            
            blocked_count = 0
            for x, y in test_points:
                result = await self.page.evaluate(f"""
                    (targetElement) => {{
                        const element = document.elementFromPoint({x}, {y});
                        if (!element) return true;
                        
                        // 检查是否是目标元素或其子元素
                        if (element === targetElement || targetElement.contains(element)) {{
                            return false;
                        }}
                        
                        // 检查遮挡元素的z-index和opacity
                        const style = window.getComputedStyle(element);
                        const zIndex = parseInt(style.zIndex) || 0;
                        const opacity = parseFloat(style.opacity) || 1;
                        
                        // 如果遮挡元素透明度很低，认为不是真正的遮挡
                        if (opacity < 0.1) return false;
                        
                        return true;
                    }}
                """, element)
                
                if result:
                    blocked_count += 1
            
            # 如果超过一半的点位被遮挡，认为元素被遮挡
            is_blocked = blocked_count > len(test_points) / 2
            
            if is_blocked:
                logger.info(f"元素被遮挡：{blocked_count}/{len(test_points)} 个检测点被遮挡")
            
            return is_blocked
            
        except Exception as e:
            logger.warning(f"检测元素遮挡状态失败: {e}")
            return False
    
    async def _handle_element_blocking(self):
        """
        增强的元素遮挡处理机制
        """
        try:
            logger.info("🔧 开始处理元素遮挡")
            
            # 1. 尝试关闭常见的遮挡元素
            await self._close_blocking_elements()
            
            # 2. 尝试滚动页面，让目标元素完全可见
            await self._scroll_to_make_visible()
            
            # 3. 尝试按ESC键关闭弹窗
            await self.page.keyboard.press('Escape')
            await asyncio.sleep(HumanBehaviorSimulator.click_delay())
            
            # 4. 点击空白区域
            await self._click_empty_position()
            
            logger.info("✅ 遮挡处理完成")
            
        except Exception as e:
            logger.warning(f"处理元素遮挡失败: {e}")
    
    async def _close_blocking_elements(self):
        """关闭常见的遮挡元素"""
        # 扩展的遮挡元素选择器
        blocking_selectors = [
            # 弹窗和模态框
            'div.d-popover', '.modal-overlay', '.popup-overlay', 
            '[role="dialog"]', '.dialog', '.modal',
            
            # 提示和通知
            '.toast', '.notification', '.alert', '.message',
            
            # 关闭按钮
            '.close-btn', '.close-button', '[aria-label="关闭"]',
            'button[title="关闭"]', '.icon-close',
            
            # 小红书特定的遮挡元素
            '.guide-mask', '.tutorial-overlay', '.intro-overlay',
            '.tips-popup', '.help-popup',
        ]
        
        for selector in blocking_selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                for element in elements:
                    if await element.is_visible():
                        # 尝试点击关闭按钮
                        if 'close' in selector or '关闭' in selector:
                            await element.click()
                            logger.info(f"点击关闭按钮: {selector}")
                        else:
                            # 移除遮挡元素
                            await element.evaluate('el => el.remove()')
                            logger.info(f"移除遮挡元素: {selector}")
                        
                        await asyncio.sleep(HumanBehaviorSimulator.click_delay())
            except:
                continue
    
    async def _scroll_to_make_visible(self):
        """滚动页面使元素完全可见"""
        try:
            # 滚动到页面顶部，然后再滚动到目标位置
            await self.page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(HumanBehaviorSimulator.mouse_move_delay())
            
            # 小幅度随机滚动，模拟用户寻找元素
            for _ in range(3):
                scroll_delta = random.randint(-200, 200)
                await self.page.evaluate(f"window.scrollBy(0, {scroll_delta})")
                await asyncio.sleep(HumanBehaviorSimulator.mouse_move_delay())
                
        except Exception as e:
            logger.warning(f"滚动页面失败: {e}")
    
    async def _click_empty_position(self):
        """
        点击页面空白区域，模拟Go版本的clickEmptyPosition
        """
        try:
            # 随机选择页面上方的空白区域
            x = 380 + random.randint(0, 100)
            y = 20 + random.randint(0, 60)
            
            await self.page.mouse.click(x, y)
            logger.info(f"点击空白位置: ({x}, {y})")
            
        except Exception as e:
            logger.warning(f"点击空白位置失败: {e}")
    
    async def human_type(self, selector: str, text: str, delay_range: Tuple[float, float] = None) -> bool:
        """
        高级人类打字模拟，包含错误修正和真实打字模式
        """
        try:
            element = await self.page.wait_for_selector(selector, timeout=10000)
            if not element:
                return False
            
            # 先点击元素获得焦点
            await self.random_click(selector)
            await asyncio.sleep(HumanBehaviorSimulator.reading_delay())
            
            # 清空现有内容
            await element.fill('')
            await asyncio.sleep(HumanBehaviorSimulator.thinking_delay())
            
            # 获取打字模式
            pattern = HumanBehaviorSimulator.get_typing_pattern(len(text))
            
            # 生成包含错误的打字动作序列
            actions = HumanBehaviorSimulator.simulate_typing_errors(text, error_rate=0.015)
            
            # 执行打字动作
            for i, action in enumerate(actions):
                if action['type'] == 'type':
                    # 使用动态延迟
                    delay = random.uniform(*pattern['base_delay'])
                    await self.page.keyboard.type(action['char'], delay=delay)
                    
                elif action['type'] == 'backspace':
                    await self.page.keyboard.press('Backspace')
                    await asyncio.sleep(random.uniform(0.1, 0.2))
                    
                elif action['type'] == 'pause':
                    await asyncio.sleep(action['duration'])
                
                # 随机暂停，模拟思考
                if random.random() < pattern['pause_probability']:
                    await asyncio.sleep(random.uniform(*pattern['pause_delay']))
                
                # 定期思考暂停
                if i > 0 and i % pattern['thinking_interval'] == 0:
                    await asyncio.sleep(random.uniform(*pattern['thinking_delay']))
                
                # 偶尔分心（降低频率和概率）
                if i > 0 and i % 100 == 0 and random.random() < 0.01:
                    await asyncio.sleep(HumanBehaviorSimulator.distraction_delay())
            
            logger.info(f"✅ 高级人类打字完成: {selector} - {len(text)}字符")
            return True
            
        except Exception as e:
            logger.error(f"❌ 高级人类打字失败: {selector} - {e}")
            return False
    
    async def smart_wait_and_click(self, selectors: List[str], timeout: int = 30000, description: str = "") -> bool:
        """
        智能等待并点击，支持多个选择器，增强页面适应性
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout / 1000:
            for selector in selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        success = await self.random_click(selector)
                        if success:
                            logger.info(f"智能点击成功: {description} - {selector}")
                            return True
                except:
                    continue
            
            await asyncio.sleep(0.5)
        
        logger.warning(f"智能点击超时: {description}")
        return False
    
    async def retry_operation(self, operation, max_retries: int = 3, delay_range: Tuple[float, float] = (1, 3), description: str = "") -> bool:
        """
        重试机制，增强容错处理
        """
        for attempt in range(max_retries):
            try:
                result = await operation()
                if result:
                    logger.info(f"操作成功: {description} (尝试 {attempt + 1}/{max_retries})")
                    return True
            except Exception as e:
                logger.warning(f"操作失败: {description} (尝试 {attempt + 1}/{max_retries}) - {e}")
            
            if attempt < max_retries - 1:
                delay = random.uniform(*delay_range)
                await asyncio.sleep(delay)
        
        logger.error(f"操作最终失败: {description}")
        return False
    
    async def init_browser(self) -> bool:
        """初始化浏览器"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright 未安装，无法使用发布功能")
            return False
        
        try:
            self.playwright = await async_playwright().start()
            
            # 随机User-Agent列表（真实的Chrome浏览器）
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
            ]
            selected_user_agent = random.choice(user_agents)
            
            # 简化的反检测浏览器参数（避免过度保护）
            browser_args = [
                '--no-first-run',
                '--disable-blink-features=AutomationControlled',
                '--disable-automation',
                '--disable-default-apps',
                '--disable-sync',
                '--no-default-browser-check',
                '--disable-dev-shm-usage',
                '--ignore-certificate-errors',
            ]
            
            # 如果是可见模式，添加窗口参数
            if not self.headless:
                browser_args.extend([
                    '--start-maximized',
                    '--disable-infobars',
                ])
            
            # 随机视口大小
            viewports = [
                {'width': 1920, 'height': 1080},
                {'width': 1366, 'height': 768},
                {'width': 1536, 'height': 864},
                {'width': 1440, 'height': 900}
            ]
            selected_viewport = random.choice(viewports)
            
            # 启动浏览器
            self.browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=self.headless,
                args=browser_args,
                viewport=selected_viewport,
                user_agent=selected_user_agent,
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
            )
            
            # 获取页面
            if len(self.browser.pages) > 0:
                self.page = self.browser.pages[0]
            else:
                self.page = await self.browser.new_page()
            
            # 注入简化的反检测脚本
            await self._inject_stealth_scripts()
            
            logger.info(f"浏览器初始化成功，用户: {self.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"浏览器初始化失败: {e}")
            return False
    
    async def _inject_stealth_scripts(self):
        """注入简化的反检测JavaScript代码"""
        try:
            # 最小化反检测脚本，避免过度保护
            stealth_script = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            if (!window.chrome) { window.chrome = { runtime: {} }; }
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            """
            
            await self.page.add_init_script(stealth_script)
            logger.info("✅ 简化反检测脚本注入成功")
            
        except Exception as e:
            logger.warning(f"⚠️ 反检测脚本注入失败: {e}")
    
    async def navigate_to_xiaohongshu(self) -> bool:
        """导航到小红书"""
        async def nav_operation():
            await self.page.goto('https://www.xiaohongshu.com', 
                                wait_until='domcontentloaded', 
                                timeout=20000)
            await asyncio.sleep(random.uniform(2, 4))
            return True
        
        return await self.retry_operation(nav_operation, description="导航到小红书")
    
    async def check_login_status(self, skip_navigation: bool = False) -> Dict:
        """检查登录状态"""
        try:
            if not skip_navigation:
                await self.navigate_to_xiaohongshu()
            
            # 等待页面加载完成
            await asyncio.sleep(random.uniform(2, 4))
            
            # 多种方式检查登录状态
            login_indicators = [
                'text=登录',
                'text=注册',
                '.login-btn',
                '[data-testid="login-button"]'
            ]
            
            # 检查是否存在登录相关按钮
            for indicator in login_indicators:
                element = await self.page.query_selector(indicator)
                if element and await element.is_visible():
                    return {
                        "logged_in": False,
                        "message": "用户未登录，请在浏览器中手动登录",
                        "confidence": "high",
                        "action_required": "manual_login" if not self.headless else "login_needed"
                    }
            
            # 检查是否存在用户相关元素（已登录状态）
            user_indicators = [
                '[data-testid="user-avatar"]',
                '.avatar',
                '.user-info',
                '.user-name',
                'text=发布笔记',
                '.publish-btn',
                '[href*="/user/"]'
            ]
            
            for indicator in user_indicators:
                element = await self.page.query_selector(indicator)
                if element and await element.is_visible():
                    logger.info("✅ 检测到已登录状态")
                    return {
                        "logged_in": True,
                        "message": "用户已登录",
                        "confidence": "high"
                    }
            
            return {
                "logged_in": False,
                "message": "登录状态不明确，建议重新登录",
                "confidence": "low",
                "action_required": "check_manually" if not self.headless else "login_needed"
            }
            
        except Exception as e:
            logger.error(f"检查登录状态失败: {e}")
            return {
                "logged_in": False,
                "message": f"检查失败: {str(e)}",
                "confidence": "low"
            }
    
    async def download_image(self, image_url: str) -> Optional[str]:
        """下载图片到本地"""
        try:
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()
            
            # 生成文件名
            parsed_url = urlparse(image_url)
            filename = os.path.basename(parsed_url.path) or f"image_{int(time.time())}.jpg"
            if not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                filename += '.jpg'
            
            file_path = self.download_dir / filename
            
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            logger.info(f"图片下载成功: {file_path}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"下载图片失败 {image_url}: {e}")
            return None
    
    async def publish_note(self, content: str, title: str, images: List[str] = None) -> Dict:
        """发布小红书笔记 - 根据是否有图片选择发布页面"""
        try:
            logger.info("🚀 开始发布小红书笔记...")
            
            # 步骤1: 根据是否有图片选择正确的发布页面
            has_images = images and len(images) > 0
            if has_images:
                logger.info("📍 步骤1: 导航到图文发布页面")
                publish_url = "https://creator.xiaohongshu.com/publish/publish?source=official"
                logger.info(f"🖼️ 检测到图片，使用图文发布模式")
            else:
                logger.info("📍 步骤1: 导航到长文发布页面")
                publish_url = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=article"
                logger.info(f"📝 无图片，使用长文发布模式")
            
            try:
                logger.info(f"🌐 访问发布页面: {publish_url}")
                # 使用更宽松的等待条件，避免因持续请求导致 networkidle 无法达成
                await self.page.goto(publish_url, wait_until='domcontentloaded', timeout=90000)
                
                # 等待页面加载
                await asyncio.sleep(3)
                
                # 检查是否需要登录
                current_url = self.page.url
                if "login" in current_url.lower() or "signin" in current_url.lower():
                    logger.info("🔐 检测到需要登录，等待用户登录...")
                    
                    if not self.headless:
                        logger.info("⏳ 等待用户在浏览器中完成登录...")
                        logger.info("📱 请扫描二维码或输入账号密码完成登录")
                        logger.info("⏰ 系统将等待3分钟，请不要关闭浏览器")
                        
                        # 给用户更多时间登录 - 3分钟
                        for i in range(180):  # 等待最多180秒（3分钟）
                            await asyncio.sleep(1)
                            
                            # 每30秒检查一次URL变化
                            if i % 30 == 0 and i > 0:
                                current_url = self.page.url
                                if "publish" in current_url and "login" not in current_url.lower():
                                    logger.info("✅ 用户登录成功！")
                                    break
                            
                            # 每30秒提示一次剩余时间
                            if i % 30 == 0:
                                remaining_time = 180 - i
                                logger.info(f"⏳ 等待登录中... (还有{remaining_time}秒)")
                        else:
                            # 最后再检查一次
                            current_url = self.page.url
                            if "login" in current_url.lower() or "signin" in current_url.lower():
                                return {
                                    "success": False,
                                    "message": "等待登录超时，请确保已在浏览器中完成登录后重新运行"
                                }
                    else:
                        return {
                            "success": False,
                            "message": "用户未登录，无法发布内容"
                        }
                
                # 重新导航到发布页面（登录后可能会跳转）
                if "publish" not in self.page.url:
                    logger.info("🔄 重新导航到发布页面")
                    await self.page.goto(publish_url, wait_until='domcontentloaded', timeout=90000)
                    await asyncio.sleep(3)
                
                logger.info(f"✅ 成功到达发布页面: {self.page.url}")
                
            except Exception as e:
                logger.error(f"❌ 导航到发布页面失败: {e}")
                return {
                    "success": False,
                    "message": f"无法访问发布页面: {str(e)}"
                }
            
            # 步骤2: 等待上传内容区域并点击"上传图文"标签页（仅图文模式）
            if has_images:
                logger.info("🎯 步骤2: 等待上传内容区域并点击'上传图文'标签页")
                
                # 等待上传内容区域出现
                try:
                    await self.page.wait_for_selector('div.upload-content', timeout=30000)
                    logger.info("✅ 找到上传内容区域")
                except Exception as e:
                    logger.error(f"❌ 未找到上传内容区域: {e}")
                    return {
                        "success": False,
                        "message": "未找到上传内容区域，可能页面结构已变化"
                    }
                
                # 点击"上传图文"标签页
                try:
                    await self._click_publish_tab("上传图文")
                    logger.info("✅ 成功点击'上传图文'标签页")
                except Exception as e:
                    logger.warning(f"⚠️ 点击'上传图文'标签页失败: {e}")
                    # 继续执行，可能已经在正确的标签页
                
                # 等待标签页切换完成
                await asyncio.sleep(2)
                
                # 步骤3: 上传图片（图文模式的关键步骤）
                logger.info("📸 步骤3: 上传图片")
                upload_success = await self._upload_images(images)
                if not upload_success:
                    return {
                        "success": False,
                        "message": "图片上传失败"
                    }
                logger.info("✅ 图片上传完成")
                
            else:
                logger.info("🎯 步骤2: 长文模式，寻找并点击'新的创作'按钮")
                
                # 等待页面完全加载
                await self._wait_for_page_ready()
                
                # 点击"新的创作"按钮
                button_clicked = await self._click_new_creation_button()
                if not button_clicked:
                    return {
                        "success": False,
                        "message": "无法找到或点击'新的创作'按钮"
                    }
                
                # 等待编辑页面加载
                await asyncio.sleep(3)
                await self._wait_for_page_ready()
            
            # 步骤4: 填写内容并发布
            logger.info("📝 步骤4: 填写内容并发布")
            return await self._fill_content_and_publish(content, title, images)
            
        except Exception as e:
            logger.error(f"发布笔记时出错: {e}")
            return {"success": False, "message": f"发布失败: {str(e)}"}
        finally:
            if self.auto_close:
                await self.close_browser()
    
    async def _upload_images(self, images: List[str]) -> bool:
        """上传图片 - 参考Go版本实现"""
        if not images:
            return True
            
        try:
            logger.info(f"📸 开始上传 {len(images)} 张图片")
            
            # 处理图片文件（支持本地路径和URL）
            valid_images = []
            for image_item in images:
                # 清理URL中的空格和引号
                image_item = image_item.strip().strip('"').strip("'").strip()
                
                if image_item.startswith(('http://', 'https://')):
                    # 处理URL图片
                    logger.info(f"🌐 检测到图片URL: {image_item}")
                    downloaded_path = await self.download_image(image_item)
                    if downloaded_path and os.path.exists(downloaded_path):
                        valid_images.append(downloaded_path)
                        logger.info(f"✅ 图片下载成功: {downloaded_path}")
                    else:
                        logger.warning(f"❌ 图片下载失败: {image_item}")
                elif os.path.exists(image_item):
                    # 处理本地文件路径
                    valid_images.append(image_item)
                    logger.info(f"✅ 找到本地图片文件: {image_item}")
                else:
                    logger.warning(f"❌ 图片文件不存在: {image_item}")
            
            if not valid_images:
                logger.warning("没有有效的图片文件")
                return False
            
            # 注意：标签页切换已在主流程中完成，直接查找上传区域
            logger.info("🎯 在上传图文标签页中查找上传区域")
            
            # 等待上传区域出现
            try:
                await self.page.wait_for_selector('.upload-content', timeout=10000)
                logger.info("✅ 找到上传区域")
            except:
                logger.warning("⚠️ 未找到上传区域，继续尝试")
            
            # 查找上传输入框 - 优先使用Go版本的选择器
            upload_selectors = [
                '.upload-input',  # Go版本使用的选择器
                'input[type="file"]',
                'input[accept*="image"]',
                '.upload-area input[type="file"]',
                '.file-input'
            ]
            
            upload_input = None
            for selector in upload_selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        upload_input = element
                        logger.info(f"✅ 找到上传输入框: {selector}")
                        break
                except:
                    continue
            
            if not upload_input:
                logger.error("❌ 未找到图片上传输入框")
                return False
            
            # 上传图片文件
            await upload_input.set_input_files(valid_images)
            logger.info(f"✅ 图片文件已设置到上传输入框")
            
            # 等待上传完成 - 使用Go版本的检测逻辑
            return await self._wait_for_upload_complete(len(valid_images))
            
        except Exception as e:
            logger.error(f"❌ 图片上传失败: {e}")
            return False
    
    async def _click_publish_tab(self, tab_name: str) -> bool:
        """点击发布标签页（对应Go版本的mustClickPublishTab）"""
        try:
            max_attempts = 75  # 15秒 / 200ms
            for attempt in range(max_attempts):
                try:
                    # 查找所有creator-tab元素
                    tab_elements = await self.page.query_selector_all('div.creator-tab')
                    
                    for tab_element in tab_elements:
                        # 检查元素是否可见
                        if not await tab_element.is_visible():
                            continue
                            
                        # 获取文本内容
                        text_content = await tab_element.text_content()
                        if text_content and text_content.strip() == tab_name:
                            # 检查元素是否被遮挡
                            if await self._is_element_blocked(tab_element):
                                logger.info("发布标签页被遮挡，尝试移除遮挡")
                                await self._remove_pop_cover()
                                await asyncio.sleep(0.2)
                                continue
                            
                            # 点击标签页
                            await tab_element.click()
                            logger.info(f"成功点击{tab_name}标签页")
                            return True
                    
                    await asyncio.sleep(0.2)
                    
                except Exception as e:
                    logger.debug(f"查找标签页失败 (尝试 {attempt + 1}): {e}")
                    await asyncio.sleep(0.2)
            
            logger.error(f"未找到发布标签页: {tab_name}")
            return False
            
        except Exception as e:
            logger.error(f"点击发布标签页时出错: {e}")
            return False

    async def _remove_pop_cover(self):
        """移除弹窗遮挡（对应Go版本的removePopCover）"""
        try:
            # 移除弹窗
            popover = await self.page.query_selector('div.d-popover')
            if popover:
                await popover.evaluate('element => element.remove()')
            
            # 点击空白位置
            await self._click_empty_position()
            
        except Exception as e:
            logger.debug(f"移除弹窗遮挡时出错: {e}")

    async def _click_empty_position(self):
        """点击空白位置（对应Go版本的clickEmptyPosition）"""
        try:
            import random
            x = 380 + random.randint(0, 100)
            y = 20 + random.randint(0, 60)
            await self.page.mouse.click(x, y)
        except Exception as e:
            logger.debug(f"点击空白位置时出错: {e}")



    async def _wait_for_upload_complete(self, expected_count: int) -> bool:
        """等待图片上传完成（对应Go版本的waitForUploadComplete）"""
        try:
            logger.info(f"⏳ 开始等待图片上传完成，期望数量: {expected_count}")
            
            max_wait_time = 60  # 最大等待60秒
            check_interval = 0.5  # 每0.5秒检查一次
            start_time = time.time()
            
            while time.time() - start_time < max_wait_time:
                try:
                    # 使用Go版本的选择器检查已上传的图片
                    uploaded_images = await self.page.query_selector_all('.img-preview-area .pr')
                    current_count = len(uploaded_images)
                    
                    logger.info(f"检测到已上传图片数量: {current_count}, 期望数量: {expected_count}")
                    
                    if current_count >= expected_count:
                        logger.info(f"✅ 所有图片上传完成，数量: {current_count}")
                        return True
                        
                except Exception as e:
                    logger.debug(f"检查上传状态时出错: {e}")
                
                await asyncio.sleep(check_interval)
            
            logger.error("❌ 上传超时，请检查网络连接和图片大小")
            return False
            
        except Exception as e:
            logger.error(f"等待图片上传完成时出错: {e}")
            return False

    async def _inject_anti_detection_script(self):
        """注入自定义反检测脚本"""
        try:
            anti_detection_script = """
            // 自定义反检测脚本
            (function() {
                // 1. 覆盖webdriver检测
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true
                });
                
                // 2. 模拟真实用户行为
                const originalAddEventListener = EventTarget.prototype.addEventListener;
                EventTarget.prototype.addEventListener = function(type, listener, options) {
                    if (type === 'mousedown' || type === 'mouseup' || type === 'click') {
                        // 添加微小的随机延迟
                        setTimeout(() => {
                            originalAddEventListener.call(this, type, listener, options);
                        }, Math.random() * 10);
                    } else {
                        originalAddEventListener.call(this, type, listener, options);
                    }
                };
                
                // 3. 模拟真实的鼠标移动轨迹
                let lastMouseX = 0, lastMouseY = 0;
                document.addEventListener('mousemove', function(e) {
                    lastMouseX = e.clientX;
                    lastMouseY = e.clientY;
                });
                
                // 4. 覆盖一些常见的自动化检测
                window.chrome = window.chrome || {};
                window.chrome.runtime = window.chrome.runtime || {};
                
                // 5. 模拟真实的键盘输入间隔
                const originalDispatchEvent = EventTarget.prototype.dispatchEvent;
                EventTarget.prototype.dispatchEvent = function(event) {
                    if (event.type === 'keydown' || event.type === 'keyup') {
                        // 添加随机延迟模拟真实输入
                        setTimeout(() => {
                            originalDispatchEvent.call(this, event);
                        }, Math.random() * 50 + 10);
                    } else {
                        originalDispatchEvent.call(this, event);
                    }
                };
                
                console.log('🛡️ 反检测脚本已注入');
            })();
            """
            
            await self.page.evaluate(anti_detection_script)
            logger.info("🛡️ 反检测脚本注入成功")
        except Exception as e:
            logger.debug(f"反检测脚本注入失败: {e}")

    async def _simulate_human_behavior(self):
        """模拟真人行为"""
        try:
            # 随机鼠标移动
            viewport = await self.page.viewport_size()
            if viewport:
                for _ in range(random.randint(2, 5)):
                    x = random.randint(100, viewport['width'] - 100)
                    y = random.randint(100, viewport['height'] - 100)
                    await self.page.mouse.move(x, y)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
            
            # 随机滚动
            scroll_distance = random.randint(-200, 200)
            await self.page.mouse.wheel(0, scroll_distance)
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            logger.debug("🤖 人类行为模拟完成")
        except Exception as e:
            logger.debug(f"人类行为模拟失败: {e}")

    async def _click_publish_tab(self, tab_text):
        """点击发布标签页（基于Go版本逻辑）"""
        try:
            logger.info(f"🎯 尝试点击'{tab_text}'标签页")
            
            # 等待上传内容区域出现（Go版本的逻辑）
            await self.page.wait_for_selector('div.upload-content', timeout=30000)
            
            # 查找所有creator-tab元素
            tab_elements = await self.page.query_selector_all('div.creator-tab')
            
            target_tab = None
            for tab_element in tab_elements:
                try:
                    # 检查元素是否可见
                    if not await tab_element.is_visible():
                        continue
                    
                    # 检查元素是否被隐藏（通过style属性）
                    style = await tab_element.get_attribute('style')
                    if style and ('left: -9999px' in style or 'position: absolute' in style):
                        logger.debug(f"跳过隐藏的标签页元素: {style}")
                        continue
                    
                    # 检查元素是否在视口内
                    bounding_box = await tab_element.bounding_box()
                    if not bounding_box or bounding_box['x'] < 0 or bounding_box['y'] < 0:
                        logger.debug(f"跳过视口外的标签页元素: {bounding_box}")
                        continue
                    
                    # 获取元素文本内容
                    text_content = await tab_element.text_content()
                    if text_content and text_content.strip() == tab_text:
                        target_tab = tab_element
                        logger.info(f"✅ 找到匹配的标签页: '{text_content.strip()}'")
                        break
                        
                except Exception as e:
                    logger.debug(f"检查标签页元素失败: {e}")
                    continue
            
            if not target_tab:
                raise Exception(f"未找到文本为'{tab_text}'的标签页")
            
            # 滚动到元素位置
            await target_tab.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)
            
            # 点击标签页
            await target_tab.click()
            logger.info(f"✅ 成功点击'{tab_text}'标签页")
            
            # 等待标签页切换完成
            await asyncio.sleep(1)
            
            # 验证点击是否成功
            logger.info(f"🔍 验证'{tab_text}'标签页点击效果...")
            try:
                # 检查页面是否有变化
                current_url = self.page.url
                logger.info(f"📍 当前页面URL: {current_url}")
                
                # 检查是否有上传相关的元素出现
                upload_elements = await self.page.query_selector_all('.upload-input, input[type="file"], [class*="upload"]')
                logger.info(f"🔍 找到 {len(upload_elements)} 个上传相关元素")
                
            except Exception as e:
                logger.debug(f"验证点击效果时出错: {e}")
            
        except Exception as e:
            logger.error(f"❌ 点击'{tab_text}'标签页失败: {e}")
            raise

    async def _wait_for_page_ready(self):
        """等待页面完全加载"""
        try:
            # 优先等待 DOM 内容加载完成
            await self.page.wait_for_load_state('domcontentloaded', timeout=20000)
            
            # 额外等待时间让动态内容渲染完成（模拟真人等待页面加载）
            page_load_delay = HumanBehaviorSimulator.page_load_delay()
            await self.page.wait_for_timeout(int(page_load_delay * 1000))
            
            # 等待页面中的JavaScript执行完成
            await self.page.evaluate("""
                () => new Promise(resolve => {
                    if (document.readyState === 'complete') {
                        resolve();
                    } else {
                        window.addEventListener('load', resolve);
                    }
                })
            """)
            
            logger.info("✅ 页面加载完成")
            
        except Exception as e:
            logger.warning(f"⚠️ 等待页面加载时出错: {e}")

    async def _analyze_page_structure(self):
        """分析页面DOM结构，帮助定位元素"""
        try:
            logger.info("🔍 分析页面DOM结构...")
            
            # 获取页面标题
            page_title = await self.page.title()
            logger.info(f"📄 页面标题: {page_title}")
            
            # 获取当前URL
            current_url = self.page.url
            logger.info(f"🔗 当前URL: {current_url}")
            
            # 分析输入框元素
            input_analysis = await self.page.evaluate("""
                () => {
                    const inputs = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]'));
                    return inputs.map(input => ({
                        tagName: input.tagName,
                        type: input.type || 'N/A',
                        placeholder: input.placeholder || 'N/A',
                        className: input.className || 'N/A',
                        id: input.id || 'N/A',
                        visible: input.offsetParent !== null,
                        textContent: input.textContent ? input.textContent.substring(0, 50) : 'N/A'
                    }));
                }
            """)
            
            logger.info("📋 页面输入框分析:")
            for i, input_info in enumerate(input_analysis):
                if input_info['visible']:
                    logger.info(f"  {i+1}. {input_info['tagName']} - type: {input_info['type']}, placeholder: {input_info['placeholder']}, class: {input_info['className']}")
            
            # 分析按钮元素
            button_analysis = await self.page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button, a[role="button"], [role="button"]'));
                    return buttons.map(button => ({
                        tagName: button.tagName,
                        textContent: button.textContent ? button.textContent.trim().substring(0, 20) : 'N/A',
                        className: button.className || 'N/A',
                        id: button.id || 'N/A',
                        visible: button.offsetParent !== null
                    }));
                }
            """)
            
            logger.info("🔘 页面按钮分析:")
            for i, button_info in enumerate(button_analysis):
                if button_info['visible'] and button_info['textContent'] != 'N/A':
                    logger.info(f"  {i+1}. {button_info['tagName']} - text: '{button_info['textContent']}', class: {button_info['className']}")
            
            # 检查是否有React或Vue等框架
            framework_info = await self.page.evaluate("""
                () => {
                    const frameworks = [];
                    if (window.React) frameworks.push('React');
                    if (window.Vue) frameworks.push('Vue');
                    if (window.angular) frameworks.push('Angular');
                    if (document.querySelector('[data-reactroot]')) frameworks.push('React (detected)');
                    if (document.querySelector('[data-v-]')) frameworks.push('Vue (detected)');
                    return frameworks;
                }
            """)
            
            if framework_info:
                logger.info(f"🔧 检测到前端框架: {', '.join(framework_info)}")
            
        except Exception as e:
            logger.warning(f"⚠️ 页面结构分析失败: {e}")

    async def _wait_for_publish_page_elements(self):
        """等待发布页面的关键元素加载"""
        try:
            logger.info("🔍 等待发布页面关键元素加载...")
            
            # 等待标题输入框
            title_selectors = [
                'textarea[placeholder*="输入标题"]',
                'input[placeholder*="标题"]',
                'input[placeholder*="title"]',
                '.title-input',
                '[data-testid="title-input"]'
            ]
            
            title_found = False
            for selector in title_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    logger.info(f"✅ 找到标题输入框: {selector}")
                    title_found = True
                    break
                except:
                    continue
            
            # 等待内容输入框
            content_selectors = [
                'div.tiptap.ProseMirror[contenteditable="true"]',
                'textarea[placeholder*="内容"]',
                'div[contenteditable="true"]',
                '.content-editor'
            ]
            
            content_found = False
            for selector in content_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    logger.info(f"✅ 找到内容输入框: {selector}")
                    content_found = True
                    break
                except:
                    continue
            
            if not title_found and not content_found:
                logger.warning("⚠️ 未找到标题或内容输入框，额外等待...")
                await self.page.wait_for_timeout(3000)
            
        except Exception as e:
            logger.warning(f"⚠️ 等待发布页面元素时出错: {e}")

    async def _fill_content_and_publish(self, content: str, title: str, images: List[str] = None) -> Dict:
        """填写内容并发布"""
        try:
            logger.info("📝 开始填写内容并发布")
            
            # 等待页面完全加载
            await self._wait_for_page_ready()
            
            # 注入反检测脚本
            await self._inject_anti_detection_script()
            
            # 模拟人类行为
            await self._simulate_human_behavior()
            
            # 等待发布页面关键元素加载
            await self._wait_for_publish_page_elements()
            
            await asyncio.sleep(random.uniform(1, 2))
            
            # 注意：图片上传已在主流程中完成，这里直接填写内容
            if images and len(images) > 0:
                logger.info("图文模式：图片已上传，开始填写内容")
            else:
                logger.info("长文模式：开始填写内容")
            
            # 步骤1: 填写标题（支持图文和长文模式）
            if title:
                title_selectors = [
                    # 长文模式优先选择器（参考备份文件）
                    'textarea[placeholder*="输入标题"]',
                    'textarea.d-text[placeholder*="输入标题"]',
                    'input[placeholder*="标题"]',
                    'input[placeholder*="title"]',
                    'input[placeholder*="Title"]',
                    'input[placeholder*="请输入标题"]',
                    '.title-input',
                    '[data-testid="title-input"]',
                    'textarea[placeholder*="标题"]',
                    'input[type="text"]:first-of-type',
                    'input[type="text"]',
                    
                    # 图文模式选择器
                    'div.d-input input',  # Go版本使用的选择器
                    
                    # 通用选择器
                    '[contenteditable="true"]',
                    '.note-title',
                    '.title-editor',
                    'textarea:not([style*="display: none"])',
                    'input:not([style*="display: none"])',
                    
                    # 更广泛的选择器
                    'textarea',
                    'input[type="text"]'
                ]
                
                title_filled = False
                for selector in title_selectors:
                    try:
                        element = await self.page.query_selector(selector)
                        if element and await element.is_visible():
                            # 智能点击，避免遮挡
                            await element.scroll_into_view_if_needed()
                            await asyncio.sleep(random.uniform(0.2, 0.5))
                            
                            # 随机坐标点击
                            box = await element.bounding_box()
                            if box:
                                x = box['x'] + random.uniform(10, box['width'] - 10)
                                y = box['y'] + random.uniform(5, box['height'] - 5)
                                await self.page.mouse.click(x, y)
                            else:
                                await element.click()
                            
                            await asyncio.sleep(random.uniform(0.3, 0.8))
                            
                            # 使用高级输入模拟
                            await element.fill('')
                            await asyncio.sleep(HumanBehaviorSimulator.thinking_delay())
                            
                            # 获取打字模式并执行高级输入
                            pattern = HumanBehaviorSimulator.get_typing_pattern(len(title))
                            actions = HumanBehaviorSimulator.simulate_typing_errors(title, error_rate=0.01)
                            
                            for i, action in enumerate(actions):
                                if action['type'] == 'type':
                                    delay = random.uniform(*pattern['base_delay'])
                                    await self.page.keyboard.type(action['char'], delay=delay)
                                elif action['type'] == 'backspace':
                                    await self.page.keyboard.press('Backspace')
                                    await asyncio.sleep(random.uniform(0.1, 0.2))
                                elif action['type'] == 'pause':
                                    await asyncio.sleep(action['duration'])
                                
                                # 随机思考暂停
                                if random.random() < pattern['pause_probability']:
                                    await asyncio.sleep(random.uniform(*pattern['pause_delay']))
                            
                            logger.info(f"✅ 标题填写完成: {title}")
                            title_filled = True
                            break
                    except Exception as e:
                        logger.debug(f"标题选择器 {selector} 失败: {e}")
                        continue
                
                if not title_filled:
                    logger.warning("未能填写标题")
            
            await asyncio.sleep(random.uniform(1, 2))
            
            # 步骤2: 填写正文内容（支持图文和长文模式）
            content_selectors = [
                # 图文模式选择器
                'div.ql-editor',  # Go版本首选的选择器
                'p[data-placeholder*="输入正文描述"]',  # Go版本的备选选择器
                
                # 长文模式选择器（参考备份文件）
                'div.tiptap.ProseMirror[contenteditable="true"]',  # 富文本编辑器
                'textarea[placeholder*="内容"]',
                'textarea[placeholder*="content"]',
                'textarea[placeholder*="正文"]',
                'textarea[placeholder*="文本"]',
                'textarea[placeholder*="输入"]',
                'textarea[placeholder*="写点什么"]',
                'textarea[placeholder*="分享"]',
                'textarea[placeholder*="小红书"]',
                'textarea[placeholder*="笔记"]',
                
                # 通用选择器
                'div[contenteditable="true"]',
                '[contenteditable="true"]',
                '.content-editor',
                '.note-editor',
                '.text-editor',
                '.editor',
                'textarea:not([style*="display: none"])',
                'div[contenteditable]:not([style*="display: none"])'
            ]
            
            content_filled = False
            for selector in content_selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        # 智能点击，避免遮挡
                        await element.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(0.3, 0.7))
                        
                        # 随机坐标点击
                        box = await element.bounding_box()
                        if box:
                            x = box['x'] + random.uniform(20, box['width'] - 20)
                            y = box['y'] + random.uniform(10, box['height'] - 10)
                            await self.page.mouse.click(x, y)
                        else:
                            await element.click()
                        
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        
                        # 对于富文本编辑器，使用键盘插入文本
                        tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
                        if tag_name == 'div' and 'contenteditable' in selector:
                            # 富文本编辑器：使用键盘插入
                            try:
                                await self.page.keyboard.insert_text(content)
                                logger.info(f"✅ 正文内容填写完成（富文本模式）: {content[:50]}...")
                                content_filled = True
                                break
                            except Exception:
                                # 回退到逐字符输入
                                pass
                        
                        # 清空现有内容并逐字符输入
                        try:
                            await element.fill('')
                        except:
                            # 对于某些富文本编辑器，fill可能不工作
                            await self.page.keyboard.press('Control+a')
                            await asyncio.sleep(0.1)
                            await self.page.keyboard.press('Delete')
                        
                        await asyncio.sleep(HumanBehaviorSimulator.thinking_delay())
                        
                        # 使用高级输入模拟输入正文内容
                        pattern = HumanBehaviorSimulator.get_typing_pattern(len(content))
                        actions = HumanBehaviorSimulator.simulate_typing_errors(content, error_rate=0.008)
                        
                        for i, action in enumerate(actions):
                            if action['type'] == 'type':
                                delay = random.uniform(*pattern['base_delay'])
                                await self.page.keyboard.type(action['char'], delay=delay)
                            elif action['type'] == 'backspace':
                                await self.page.keyboard.press('Backspace')
                                await asyncio.sleep(random.uniform(0.1, 0.2))
                            elif action['type'] == 'pause':
                                await asyncio.sleep(action['duration'])
                            
                            # 随机思考暂停
                            if random.random() < pattern['pause_probability']:
                                await asyncio.sleep(random.uniform(*pattern['pause_delay']))
                            
                            # 定期思考暂停
                            if i > 0 and i % pattern['thinking_interval'] == 0:
                                await asyncio.sleep(random.uniform(*pattern['thinking_delay']))
                            
                            # 长文本分心暂停（降低频率）
                            if i > 0 and i % 200 == 0 and random.random() < 0.01:
                                await asyncio.sleep(HumanBehaviorSimulator.distraction_delay())
                        
                        logger.info(f"✅ 正文内容填写完成: {content[:50]}...")
                        content_filled = True
                        break
                except Exception as e:
                    logger.debug(f"内容选择器 {selector} 失败: {e}")
                    continue
            
            if not content_filled:
                return {"success": False, "message": "找不到正文内容输入框"}
            
            await asyncio.sleep(random.uniform(1, 2))
            
            # 步骤3: 点击一键排版按钮（如果存在）
            layout_selectors = [
                # 基于用户提供的HTML结构
                'button:has-text("一键排版")',
                'button[class*="d-button"][class*="next-btn"]:has-text("一键排版")',
                'button[class*="custom-button"][class*="bg-red"]:has-text("一键排版")',
                'span[class*="next-btn-text"]:has-text("一键排版")',
                'div.footer button:has-text("一键排版")',
                # 原有选择器
                'button[title*="排版"]',
                '.layout-btn',
                '.format-btn'
            ]
            
            await self._click_button_with_selectors("一键排版", layout_selectors, required=False)
            
            # 步骤4: 点击下一步按钮（如果存在）
            next_selectors = [
                # 基于用户提供的HTML结构
                'button:has-text("下一步")',
                'button[class*="d-button-large"][class*="submit"]:has-text("下一步")',
                'button[class*="d-button"][class*="--color-bg-primary"]:has-text("下一步")',
                'span[class*="d-text"]:has-text("下一步")',
                'div.footer button:has-text("下一步")',
                # 原有选择器
                'button:has-text("继续")',
                'button:has-text("Next")',
                '.next-btn',
                '.continue-btn'
            ]
            
            await self._click_button_with_selectors("下一步", next_selectors, required=False)
            
            # 步骤5: 点击发布按钮（改进版本）
            publish_selectors = [
                # 基于用户提供的HTML结构
                'button[class*="publishBtn"]:has-text("发布")',
                'button[class*="d-button-large"][class*="red"]:has-text("发布")',
                'button[data-impression*="note_compose_target"]:has-text("发布")',
                'div.submit button:has-text("发布")',
                'span[class*="d-text"]:has-text("发布")',
                # 原有选择器
                'div.submit div.d-button-content',  # Go版本使用的选择器
                'button:has-text("发布")',
                'button:has-text("发表")',
                'div.submit button',
                'button[class*="submit"]',
                # 长文模式额外选择器
                'button:has-text("发布笔记")',
                'button:has-text("立即发布")',
                'button:has-text("确认发布")',
                'button[type="submit"]',
                '.publish-btn',
                '.submit-btn'
            ]
            
            # 查找发布按钮（跳过禁用的）
            publish_locator = None
            for selector in publish_selectors:
                try:
                    elements = await self.page.query_selector_all(selector)
                    for element in elements:
                        if await element.is_visible():
                            # 检查是否禁用
                            try:
                                is_disabled = await element.evaluate("el => !!(el.disabled || el.getAttribute('disabled'))")
                            except Exception:
                                is_disabled = False
                            if not is_disabled:
                                publish_locator = element
                                logger.info(f"✅ 找到可用发布按钮: {selector}")
                                break
                    if publish_locator:
                        break
                except Exception as e:
                    logger.debug(f"发布按钮选择器失败 {selector}: {e}")
                    continue
            
            publish_clicked = False
            if publish_locator:
                try:
                    # 滚动到视图中
                    await publish_locator.scroll_into_view_if_needed()
                    
                    # 等待按钮可见
                    await asyncio.sleep(0.5)
                    
                    # 轮询禁用状态
                    for _ in range(10):
                        try:
                            disabled = await publish_locator.evaluate(
                                "el => !!(el.disabled || el.getAttribute('disabled') || el.getAttribute('aria-disabled') === 'true')"
                            )
                        except Exception:
                            disabled = False
                        if not disabled:
                            break
                        await asyncio.sleep(0.3)
                    
                    # 先hover，触发可能的样式与事件
                    try:
                        await publish_locator.hover()
                        await asyncio.sleep(0.2)
                    except Exception:
                        pass
                    
                    # 首选正常点击
                    try:
                        await publish_locator.click()
                        logger.info("✅ 已点击发布按钮（正常点击）")
                        publish_clicked = True
                    except Exception as e:
                        logger.warning(f"⚠️ 正常点击失败，尝试强制点击: {e}")
                        try:
                            await publish_locator.click(force=True)
                            logger.info("✅ 已点击发布按钮（强制点击）")
                            publish_clicked = True
                        except Exception as e2:
                            logger.warning(f"⚠️ 强制点击失败，尝试事件派发: {e2}")
                            try:
                                await publish_locator.evaluate(
                                    "el => { el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true})); el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true})); el.dispatchEvent(new MouseEvent('click', {bubbles:true})); }"
                                )
                                logger.info("✅ 已点击发布按钮（事件派发）")
                                publish_clicked = True
                            except Exception as e3:
                                logger.error(f"❌ 事件派发点击失败: {e3}")
                except Exception as e:
                    logger.error(f"❌ 发布按钮点击过程失败: {e}")
            
            # 基于可访问性角色的回退
            if not publish_clicked:
                try:
                    btn_locator = self.page.get_by_role("button", name=re.compile("(发布|确认发布|立即发布)"))
                    count = await btn_locator.count()
                    if count > 0:
                        target = btn_locator.first
                        await target.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)
                        await target.click()
                        logger.info("✅ 通过角色名点击发布按钮")
                        publish_clicked = True
                except Exception as e:
                    logger.debug(f"基于角色查找发布按钮失败: {e}")
            
            # XPath回退
            if not publish_clicked:
                try:
                    xpath_locator = self.page.locator('xpath=//span[contains(normalize-space(.), "发布")]/ancestor::button[1]')
                    if await xpath_locator.count() > 0:
                        target = xpath_locator.first
                        await target.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)
                        await target.click()
                        logger.info("✅ 通过XPath点击发布按钮")
                        publish_clicked = True
                except Exception as e:
                    logger.debug(f"XPath 查找发布按钮失败: {e}")
            
            if publish_clicked:
                # 点击后稍作等待，等待提交或弹窗动作 - 参考备份版本
                await self._wait_for_page_ready()
                await asyncio.sleep(random.uniform(0.8, 1.5))
                
                # 等待发布完成
                await asyncio.sleep(5)
                
                # 检查发布结果 - 参考备份版本的简洁逻辑
                success_indicators = [
                    'text=发布成功',
                    'text=发表成功',
                    'text=提交成功',
                    'text=已发布',
                    '[class*="success"]'
                ]
                
                # 检查是否有明确的成功指示器
                for indicator in success_indicators:
                    try:
                        element = await self.page.query_selector(indicator)
                        if element and await element.is_visible():
                            logger.info("🎉 笔记发布成功！")
                            return {
                                "success": True,
                                "message": "笔记发布成功",
                                "title": title,
                                "content": content,
                                "images_count": len(images) if images else 0
                            }
                    except:
                        continue
                
                # 如果没有明确的成功提示，假设发布成功 - 参考备份版本
                logger.info("✅ 发布操作完成")
                return {
                    "success": True,
                    "message": "笔记发布完成",
                    "title": title,
                    "content": content,
                    "images_count": len(images) if images else 0
                }
            else:
                return {"success": False, "message": "找不到发布按钮"}
                
        except Exception as e:
            logger.error(f"填写内容并发布失败: {e}")
            return {"success": False, "message": f"发布失败: {str(e)}"}
    
    async def _click_new_creation_button(self) -> bool:
        """点击'新的创作'按钮 - 长文模式专用"""
        try:
            logger.info("🔍 寻找'新的创作'按钮...")
            
            # 定义"新的创作"按钮的多种选择器
            new_creation_selectors = [
                # 基于用户提供的HTML结构
                'button:has-text("新的创作")',
                'button[class*="new-btn"]:has-text("新的创作")',
                'button[data-v-52f51a04]:has-text("新的创作")',
                
                # 通用选择器
                'button:has-text("新的创作")',
                'button:has-text("创作")',
                'button:has-text("写长文")',
                'button:has-text("发布")',
                
                # CSS类选择器
                'button.new-btn',
                'button[class*="new"]',
                'button[class*="create"]',
                'button[class*="publish"]',
                
                # 包含SVG图标的按钮
                'button:has(svg)',
                'button:has(span:has-text("新的创作"))',
                
                # 更具体的选择器
                'div[class*="summary-content"] button',
                'div[class*="content"] button:first-child',
            ]
            
            for selector in new_creation_selectors:
                try:
                    logger.info(f"🔍 尝试选择器: {selector}")
                    
                    # 等待元素出现
                    await self.page.wait_for_selector(selector, timeout=5000)
                    
                    # 检查元素是否可见
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        logger.info(f"✅ 找到'新的创作'按钮: {selector}")
                        
                        # 滚动到元素位置
                        await element.scroll_into_view_if_needed()
                        await asyncio.sleep(1)
                        
                        # 点击按钮
                        await element.click()
                        logger.info("🎯 成功点击'新的创作'按钮")
                        
                        return True
                        
                except Exception as e:
                    logger.debug(f"选择器 {selector} 失败: {e}")
                    continue
            
            # 如果找不到按钮，尝试直接导航到编辑页面
            logger.warning("⚠️ 未找到'新的创作'按钮，尝试直接进入编辑页面")
            edit_urls = [
                "https://creator.xiaohongshu.com/publish/publish?type=article",
                "https://creator.xiaohongshu.com/publish/article",
                "https://creator.xiaohongshu.com/editor"
            ]
            
            for url in edit_urls:
                try:
                    await self.page.goto(url, wait_until='domcontentloaded', timeout=90000)
                    await asyncio.sleep(2)
                    
                    # 检查是否有编辑器
                    if await self._check_editor_presence():
                        logger.info(f"✅ 成功进入编辑页面: {url}")
                        return True
                except Exception as e:
                    logger.debug(f"尝试 {url} 失败: {e}")
                    continue
            
            return False
            
        except Exception as e:
            logger.error(f"点击'新的创作'按钮失败: {e}")
            return False
    
    async def _check_editor_presence(self) -> bool:
        """检查编辑器是否存在"""
        try:
            # 检查常见的编辑器元素
            editor_selectors = [
                'textarea[placeholder*="输入标题"]',
                'div[contenteditable="true"]',
                '.editor',
                '.tiptap',
                'textarea',
                'input[placeholder*="标题"]'
            ]
            
            for selector in editor_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    return True
                except:
                    continue
            
            return False
        except Exception as e:
            logger.debug(f"检查编辑器失败: {e}")
            return False

    async def _click_button_with_selectors(self, button_name: str, selectors: List[str], required: bool = False) -> bool:
        """通用按钮点击方法"""
        try:
            logger.info(f"🔍 寻找并点击『{button_name}』按钮")
            
            for selector in selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        # 智能点击，避免遮挡
                        await element.scroll_into_view_if_needed()
                        await asyncio.sleep(HumanBehaviorSimulator.reading_delay())
                        
                        # 模拟用户观察按钮（思考延迟）
                        await asyncio.sleep(HumanBehaviorSimulator.thinking_delay())
                        
                        # 使用智能坐标生成（模拟真人点击习惯）
                        box = await element.bounding_box()
                        if box:
                            # 使用智能坐标生成
                            x, y = HumanBehaviorSimulator.generate_human_click_coordinates(box)
                            
                            # 获取当前鼠标位置
                            current_mouse = await self.page.evaluate("() => ({ x: 0, y: 0 })")
                            
                            # 生成真实的鼠标移动路径
                            mouse_path = HumanBehaviorSimulator.generate_mouse_path(
                                current_mouse.get('x', 0), current_mouse.get('y', 0), x, y
                            )
                            
                            # 沿路径移动鼠标
                            for path_x, path_y in mouse_path[:-1]:
                                await self.page.mouse.move(path_x, path_y)
                                await asyncio.sleep(random.uniform(0.02, 0.08))
                            
                            # 最终移动到目标位置
                            await self.page.mouse.move(x, y)
                            await asyncio.sleep(HumanBehaviorSimulator.mouse_move_delay())
                            
                            # 可能的犹豫
                            if HumanBehaviorSimulator.random_pause():
                                await asyncio.sleep(HumanBehaviorSimulator.hesitation_delay())
                            
                            await self.page.mouse.click(x, y)
                        else:
                            await element.click()
                        
                        logger.info(f"✅ 『{button_name}』按钮点击完成")
                        # 按钮序列操作延迟
                        await asyncio.sleep(HumanBehaviorSimulator.button_sequence_delay())
                        return True
                except Exception as e:
                    logger.debug(f"『{button_name}』选择器失败 {selector}: {e}")
                    continue
            
            if required:
                logger.error(f"❌ 未找到『{button_name}』按钮")
                return False
            else:
                logger.warning(f"⚠️ 未找到『{button_name}』按钮，继续执行")
                return True
                
        except Exception as e:
            logger.error(f"❌ 点击『{button_name}』按钮失败: {e}")
            return False

    async def close_browser(self):
        """关闭浏览器"""
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
                self.page = None
                logger.info("浏览器已关闭")
            
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
                
        except Exception as e:
            logger.error(f"关闭浏览器时出错: {e}")
    
    def __del__(self):
        """析构函数"""
        try:
            if self.browser:
                asyncio.create_task(self.close_browser())
        except:
            pass