"""
小红书发布器 - 基于 Selenium 的真实浏览器自动化
"""
import json
import time
import os
import threading
from typing import Any, Dict, List, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from utils import get_logger

logger = get_logger("XiaohongshuSeleniumPublisher")


class XiaohongshuSeleniumPublisher:
    """使用 Selenium 自动化发布到小红书"""

    BASE_DELAY = 3
    LONG_DELAY = 6
    EDITOR_URL_KEYWORDS = [
        "creator.xiaohongshu.com/publish/publish",
        "creator.xiaohongshu.com/publish/article",
        "creator.xiaohongshu.com/creatorcenter/publish",
    ]
    LOGIN_URL_KEYWORDS = [
        "passport.xiaohongshu.com",
        "login.xiaohongshu.com",
        "account.xiaohongshu.com",
    ]
    SUCCESS_KEYWORDS = ["发布成功", "提交成功", "审核中", "发布完成"]
    NEW_CREATION_BUTTON_TEXTS = ["新的创作", "开始创作", "新建创作", "立即创作"]
    ARTICLE_ENTRY_TEXTS = ["图文", "图文笔记", "图文创作", "发笔记", "写笔记"]
    LAYOUT_BUTTON_TEXTS = ["一键排版", "智能排版", "自动排版"]
    PREVIEW_NEXT_BUTTON_TEXTS = ["下一步", "下一步发布", "下一步，发布", "下一步（发布）"]
    PUBLISH_BUTTON_TEXTS = ["发布"]
    API_BASE = "https://edith.xiaohongshu.com"
    LAYOUT_API = f"{API_BASE}/web_api/sns/v6/creator/long_text/edit/summary/generate?_proxy_timeout=600000"
    ARTICLE_IMAGES_API = f"{API_BASE}/web_api/sns/v6/creator/long_text/article/images?_proxy_timeout=600000"
    PUBLISH_API = f"{API_BASE}/web_api/sns/v2/note"
    DEFAULT_ALBUM_ID = 7

    def __init__(self, cookie: str):
        self.cookie = cookie
        self.driver = None
        self._close_pending = False
        self._close_thread = None

    def _pause(self, seconds: Optional[float] = None):
        """统一的等待方法，便于整体调慢节奏"""
        try:
            time.sleep(seconds if seconds is not None else self.BASE_DELAY)
        except Exception:
            pass

    def _scroll_to_bottom(self, repeat: int = 1):
        if not self.driver:
            return
        repeat = max(1, repeat)
        for _ in range(repeat):
            try:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                break
            time.sleep(0.5)

    def _parse_cookie_string(self) -> List[Dict[str, str]]:
        cookies: List[Dict[str, str]] = []
        raw = (self.cookie or "").strip()
        if not raw:
            return cookies
        for part in raw.split(';'):
            piece = part.strip()
            if not piece or '=' not in piece:
                continue
            name, value = piece.split('=', 1)
            cookies.append({
                "name": name.strip(),
                "value": value.strip()
            })
        return cookies

    def _inject_cookies(self, cookies: List[Dict[str, str]], domain: str) -> int:
        if not self.driver or not cookies:
            return 0
        success = 0
        for item in cookies:
            cookie_dict = {
                "name": item.get("name"),
                "value": item.get("value"),
                "domain": domain,
                "path": "/"
            }
            try:
                if not cookie_dict["name"]:
                    continue
                self.driver.add_cookie(cookie_dict)
                success += 1
            except Exception as err:
                logger.debug(f"写入 Cookie 失败 ({cookie_dict['name']}@{domain}): {err}")
        logger.info(f"已向 {domain} 写入 {success}/{len(cookies)} 个 Cookie")
        return success

    def _build_longtext_doc(self, title: str, content: str) -> Dict[str, Any]:
        paragraphs: List[Dict[str, Any]] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                paragraphs.append({"type": "paragraph", "content": []})
                continue
            paragraphs.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": line}]
            })
        if not paragraphs:
            paragraphs = [{"type": "paragraph", "content": []}]
        return {
            "title": title,
            "content": {
                "type": "doc",
                "content": paragraphs
            }
        }

    def _fallback_article_content(self, title: str, content: str) -> Dict[str, Any]:
        doc = self._build_longtext_doc(title, content)
        card_content = [
            {
                "type": "articleTitle",
                "attrs": {
                    "uuid": None,
                    "author": "",
                    "articleTitle": title,
                    "readingStats": ""
                }
            }
        ] + doc["content"]["content"]

        color_map = {
            "fc_0": "#FFFFFF",
            "fc_1": "#272727",
            "fc_2": "#EFEFEF",
            "fc_3": "#1C1C1C",
            "fc_4": "#FFFFFF",
            "fc_5": "#1C1C1C",
            "fc_6": "#272727",
            "fc_7": "#EFEFEF",
            "bgInnerColor": "#FFFFFF",
            "bgCoverColor": "#FFFFFF"
        }

        cover = {
            "titleText": title,
            "authorText": "",
            "summeryText": "",
            "readingStats": "",
            "wordNum": len(content),
            "costTime": max(len(content) // 200, 1),
            "imgPath": "",
            "coverImages": [],
            "darkMode": False,
            "authorDarkMode": False,
            "titleDarkMode": False,
            "styleType": 0
        }

        return {
            "config": {
                "colorMap": color_map,
                "cover": cover,
                "themeId": 6
            },
            "cards": [
                {
                    "type": "doc",
                    "content": card_content
                }
            ]
        }

    def _post_creator_api(self, url: str, payload: Dict[str, Any], description: str, timeout: int = 120) -> Optional[Dict[str, Any]]:
        if not self.driver:
            return None
        script = """
            const url = arguments[0];
            const body = arguments[1];
            const timeoutMs = arguments[2];
            const done = arguments[3];
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            fetch(url, {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(body),
                signal: controller.signal
            }).then(resp => resp.text().then(text => {
                clearTimeout(timer);
                let data = null;
                try {
                    data = JSON.parse(text);
                } catch (err) {
                    data = { raw: text };
                }
                done({ ok: resp.ok, status: resp.status, data });
            })).catch(error => {
                clearTimeout(timer);
                done({ ok: false, status: 0, error: error ? error.toString() : 'unknown error' });
            });
        """

        try:
            logger.info(f"尝试调用接口：{description} -> {url}")
            result = self.driver.execute_async_script(script, url, payload, max(timeout, 5) * 1000)
        except Exception as exec_err:
            logger.warning(f"调用 {description} 接口失败: {exec_err}")
            return None

        if not result:
            logger.warning(f"{description} 接口无返回")
            return None

        if not result.get("ok"):
            logger.warning(f"{description} 接口返回异常: {result}")
            return None

        return result.get("data") or {}

    def _extract_image_file_ids(self, image_data: Dict[str, Any]) -> List[str]:
        file_ids: List[str] = []
        candidates = [
            image_data.get("image_file_ids"),
            image_data.get("imageFileIds"),
            image_data.get("image_ids"),
            image_data.get("imageIds"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            if isinstance(candidate, list):
                file_ids.extend(candidate)
            elif isinstance(candidate, str):
                file_ids.append(candidate)
        return file_ids

    def _build_publish_payload(
        self,
        title: str,
        content: str,
        tags: Optional[List[str]],
        image_file_ids: List[str],
        album_id: int
    ) -> Dict[str, Any]:
        tags = tags or []
        context = {
            "longTextToImage": {
                "albumId": album_id,
                "imageFileIds": image_file_ids
            },
            "recommend_title": {
                "recommend_title_id": "",
                "is_use": 3,
                "used_index": -1
            },
            "recommend_topics": {
                "used": []
            }
        }

        hash_tags = [{"id": "", "name": tag} for tag in tags]
        desc_text = content
        images_block = [
            {
                "file_id": file_id,
                "width": 1440,
                "height": 2400,
                "metadata": {"source": -1},
                "stickers": {"version": 2, "floating": []},
                "extra_info_json": json.dumps({"mimeType": "image/png", "image_metadata": {"bg_color": "#FFFFFF"}})
            }
            for file_id in image_file_ids
        ]

        source_info = json.dumps({
            "type": "web",
            "ids": "",
            "extraInfo": json.dumps({"subType": "official", "systemId": "web"})
        })

        business_binds = json.dumps({
            "version": 1,
            "noteId": 0,
            "bizType": 0,
            "noteOrderBind": {},
            "notePostTiming": {},
            "noteCollectionBind": {"id": ""},
            "noteSketchCollectionBind": {"id": ""},
            "coProduceBind": {"enable": True},
            "noteCopyBind": {"copyable": True},
            "interactionPermissionBind": {"commentPermission": 0},
            "optionRelationList": []
        })

        return {
            "common": {
                "type": "normal",
                "note_id": "",
                "source": source_info,
                "title": title,
                "desc": desc_text,
                "ats": [],
                "hash_tag": hash_tags,
                "business_binds": business_binds,
                "privacy_info": {"op_type": 1, "type": 0, "user_ids": []},
                "goods_info": {},
                "biz_relations": [],
                "capa_trace_info": {
                    "contextJson": json.dumps(context, ensure_ascii=False)
                }
            },
            "image_info": {
                "images": images_block
            },
            "video_info": None
        }

    def _publish_via_long_text_api(self, title: str, content: str, tags: Optional[List[str]]) -> Optional[str]:
        try:
            current_url = self.driver.current_url if self.driver else ""
        except Exception:
            current_url = ""

        if "creator.xiaohongshu.com" not in current_url:
            logger.debug("当前不在创作平台页面，跳过接口直发逻辑")
            return None

        logger.info("尝试直接调用接口完成『一键排版→下一步→发布』流程…")
        doc_payload = self._build_longtext_doc(title, content)
        layout_payload = {"content": json.dumps(doc_payload, ensure_ascii=False)}

        layout_resp = self._post_creator_api(self.LAYOUT_API, layout_payload, "一键排版", timeout=90)
        if not layout_resp:
            logger.warning("接口方式『一键排版』失败，回退至界面点击方案")
            return None

        layout_data = layout_resp.get("data") or layout_resp
        album_id = layout_data.get("album_id") or layout_data.get("albumId") or self.DEFAULT_ALBUM_ID
        article_content = layout_data.get("article_content") or layout_data.get("articleContent")

        if not article_content:
            article_content = self._fallback_article_content(title, content)
        if isinstance(article_content, dict):
            article_content_str = json.dumps(article_content, ensure_ascii=False)
        else:
            article_content_str = article_content

        images_payload = {
            "article_content": article_content_str,
            "album_id": album_id
        }
        image_resp = self._post_creator_api(self.ARTICLE_IMAGES_API, images_payload, "排版预览", timeout=120)
        if not image_resp:
            logger.warning("生成排版图片失败，将继续使用界面自动化")
            return None

        image_data = image_resp.get("data") or image_resp
        image_file_ids = self._extract_image_file_ids(image_data)
        if not image_file_ids:
            logger.warning("接口返回中未包含图片 file_id，回退至界面自动化")
            return None

        publish_payload = self._build_publish_payload(title, content, tags, image_file_ids, album_id)
        publish_resp = self._post_creator_api(self.PUBLISH_API, publish_payload, "发布笔记", timeout=180)
        if not publish_resp:
            logger.warning("接口发布失败，继续使用界面自动化")
            return None

        publish_data = publish_resp.get("data") or publish_resp
        note_id = publish_data.get("note_id") or publish_data.get("noteId") or publish_data.get("id")
        if note_id:
            logger.info(f"✅ 已通过接口直接发布，note_id={note_id}")
            return str(note_id)

        logger.warning(f"接口发布返回异常: {publish_resp}")
        return None
    
    def _init_driver(self):
        """初始化浏览器驱动"""
        if self.driver:
            return
        
        try:
            chrome_options = Options()
            # chrome_options.add_argument('--headless')  # 无头模式（测试时建议关闭以观察过程）
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # 使用 webdriver-manager 自动管理驱动
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # 隐藏 webdriver 特征
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            })
            
            logger.info("Chrome 浏览器驱动初始化成功")
        except Exception as e:
            logger.error(f"初始化浏览器失败: {e}")
            raise
        
        cookie_items = self._parse_cookie_string()
        if not cookie_items:
            logger.warning("⚠️ 未解析到有效 Cookie，后续可能需要手动登录")

        # 先在主站设置通用 Cookie
        self.driver.get('https://www.xiaohongshu.com')
        self._pause(self.LONG_DELAY)
        self.driver.delete_all_cookies()
        if cookie_items:
            self._inject_cookies(cookie_items, '.xiaohongshu.com')
            self.driver.refresh()
            self._pause(self.BASE_DELAY)

        # 再切到创作中心域名补充 Creator 相关 Cookie
        self.driver.get('https://creator.xiaohongshu.com')
        self._pause(self.BASE_DELAY)
        if cookie_items:
            self._inject_cookies(cookie_items, 'creator.xiaohongshu.com')
            self.driver.refresh()
            self._pause(self.BASE_DELAY)

        logger.info("浏览器驱动初始化完成")

    def _switch_to_latest_window(self, reason: str = "") -> bool:
        """尝试聚焦最新弹出的窗口/标签页"""
        if not self.driver:
            return False
        try:
            handles = self.driver.window_handles
            if not handles:
                return False
            target_handle = handles[-1]
            if self.driver.current_window_handle != target_handle:
                self.driver.switch_to.window(target_handle)
                if reason:
                    logger.info(f"已切换到最新标签页: {reason}")
                else:
                    logger.info("已切换到最新标签页")
                return True
        except Exception as switch_err:
            logger.debug(f"切换窗口失败: {switch_err}")
        return False

    def _wait_for_editor_ready(self, timeout: int = 90) -> bool:
        """等待跳转到图文编辑器，并在需要时提示用户手动配合"""
        logger.info("等待图文编辑器加载/跳转，如果页面有提示请手动确认或登录")
        deadline = time.time() + timeout
        last_state = None

        while time.time() < deadline:
            self._switch_to_latest_window()
            try:
                current_url = self.driver.current_url
            except Exception:
                current_url = ""

            if any(keyword in current_url for keyword in self.EDITOR_URL_KEYWORDS):
                logger.info(f"✅ 已进入图文编辑器: {current_url}")
                return True

            if any(keyword in current_url for keyword in self.LOGIN_URL_KEYWORDS):
                if last_state != "login":
                    logger.warning("检测到登录页面，请在浏览器中完成扫码/短信等登录操作，完成后程序会自动继续")
                    last_state = "login"
            elif "creator.xiaohongshu.com" in current_url:
                if last_state != "creator_home":
                    logger.info("在创作服务平台主页，如未自动打开编辑器，请点击左侧『发布内容』→『图文』")
                    last_state = "creator_home"
            else:
                if last_state != "waiting":
                    logger.info(f"等待页面跳转，当前 URL: {current_url or '未知'}")
                    last_state = "waiting"

            time.sleep(2)

        logger.error("等待图文编辑器超时，请确认是否已打开图文发布页面")
        return False

    def _safe_click(self, element, description: str = "") -> bool:
        """安全地点击元素，必要时退回 JS 点击"""
        if not element:
            return False
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
            time.sleep(0.3)
            element.click()
            if description:
                logger.info(f"已点击: {description}")
            return True
        except Exception as direct_err:
            logger.debug(f"直接点击失败，尝试 JS 点击: {direct_err}")
            try:
                self.driver.execute_script("arguments[0].click();", element)
                if description:
                    logger.info(f"已通过 JS 点击: {description}")
                return True
            except Exception as js_err:
                logger.warning(f"点击元素失败: {js_err}")
        return False

    def _find_clickable_by_text(self, keywords: List[str]):
        """通过文本查找可点击控件"""
        if not self.driver:
            return None
        script = """
            const keywords = arguments[0];
            const selectors = ['button', 'div[role="button"]', 'span', 'a', 'div'];
            function match(el) {
                if (!el) return false;
                const text = (el.innerText || el.textContent || '').trim();
                if (!text) return false;
                return keywords.some(k => text.includes(k));
            }
            for (const selector of selectors) {
                const nodes = Array.from(document.querySelectorAll(selector));
                for (const node of nodes) {
                    const visible = node.offsetParent !== null || node.getClientRects().length > 0;
                    if (visible && match(node)) {
                        return node;
                    }
                }
            }
            const allNodes = Array.from(document.querySelectorAll('*'));
            for (const node of allNodes) {
                const visible = node.offsetParent !== null || node.getClientRects().length > 0;
                if (visible && match(node)) {
                    return node;
                }
            }
            return null;
        """
        try:
            return self.driver.execute_script(script, keywords)
        except Exception as err:
            logger.debug(f"查找文本元素失败: {err}")
            return None

    def _click_button_with_texts(self, keywords: List[str], description: str = "", timeout: int = 30) -> bool:
        """在指定时间内查找并点击包含关键词的按钮"""
        if not self.driver:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._switch_to_latest_window()
            button = self._find_clickable_by_text(keywords)
            if button and self._safe_click(button, description):
                return True
            self._pause(1.5)
        return False

    def _click_by_xpath(self, xpath_list: List[str], description: str = "", timeout: int = 30) -> bool:
        if not self.driver:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._switch_to_latest_window()
            for xpath in xpath_list:
                try:
                    element = WebDriverWait(self.driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    if element and self._safe_click(element, description):
                        return True
                except Exception:
                    continue
            self._pause(1.0)
        return False

    def _wait_for_final_publish_view(self, timeout: int = 90) -> bool:
        if not self.driver:
            return False
        logger.info("等待预览页加载最终『发布』按钮...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._switch_to_latest_window("预览页面")
            try:
                ready_state = self.driver.execute_script("return document.readyState")
            except Exception:
                ready_state = ""

            try:
                has_publish = self.driver.execute_script("""
                    const keywords = ['发布', '确认发布', '立即发布', '完成发布'];
                    const nodes = Array.from(document.querySelectorAll('button, div[role="button"], a'));
                    for (const node of nodes) {
                        if (!node) continue;
                        const style = window.getComputedStyle(node);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        const text = (node.innerText || node.textContent || '').trim();
                        if (!text) continue;
                        if (keywords.some(k => text.includes(k))) {
                            const rect = node.getBoundingClientRect();
                            return { found: true, top: rect.top, bottom: rect.bottom };
                        }
                    }
                    return { found: false };
                """)
            except Exception:
                has_publish = {"found": False}

            if has_publish.get("found"):
                logger.info("✅ 检测到最终发布按钮区域，准备点击")
                return True

            if ready_state == "complete":
                self._scroll_to_bottom()
            time.sleep(1.2)

        logger.warning("⚠️  等待最终发布按钮超时，可能需要手动查看新页面")
        return False

    def _is_editor_visible(self) -> bool:
        """检测是否已经出现可编辑区域"""
        if not self.driver:
            return False
        script = """
            const editables = Array.from(document.querySelectorAll('[contenteditable="true"]'));
            for (const el of editables) {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent !== null && rect.height > 80) {
                    return true;
                }
            }
            const titleInputs = Array.from(document.querySelectorAll('input, textarea'))
                .filter(el => /标题|title/.test(el.placeholder || '') && el.offsetParent !== null);
            if (titleInputs.length > 0) {
                return true;
            }
            return false;
        """
        try:
            return bool(self.driver.execute_script(script))
        except Exception as err:
            logger.debug(f"检测编辑器失败: {err}")
            return False

    def _enter_new_creation_flow(self, timeout: int = 60) -> bool:
        """如果需要，自动点击“新的创作/图文”入口进入编辑页面"""
        logger.info("检查是否需要点击『新的创作』或『图文』入口...")
        deadline = time.time() + timeout
        notified = False

        while time.time() < deadline:
            self._switch_to_latest_window()
            if self._is_editor_visible():
                logger.info("✅ 已检测到编辑器，可开始填写内容")
                return True

            new_btn = self._find_clickable_by_text(self.NEW_CREATION_BUTTON_TEXTS)
            if new_btn:
                if self._safe_click(new_btn, "新的创作"):
                    self._pause()
                    continue

            article_btn = self._find_clickable_by_text(self.ARTICLE_ENTRY_TEXTS)
            if article_btn:
                if self._safe_click(article_btn, "图文入口"):
                    self._pause()
                    continue

            if not notified:
                logger.info("未自动定位到入口，如页面出现『新的创作』或『图文』按钮，请手动点击一次，程序会继续")
                notified = True
            self._pause(1.5)

        logger.warning("未在预期时间内进入编辑器，请确认页面状态后重试")
        return self._is_editor_visible()

    def _find_content_area(self, title_element=None):
        """通过多种策略定位内容输入区域"""
        if not self.driver:
            return None
        script = """
            const titleEl = arguments[0];
            function isVisible(el) {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.visibility === 'hidden' || style.display === 'none') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }

            const prioritySelectors = [
                'div[contenteditable="true"][data-placeholder*="内容"]',
                'div[contenteditable="true"][data-placeholder*="正文"]',
                'textarea[placeholder*="内容"]',
                'textarea[placeholder*="正文"]',
                '.ql-editor[contenteditable="true"]',
                'div.rich-text-editor',
                'div.note-content',
                '.public-DraftEditor-content',
                'div[class*="ql-editor"]',
                'div[class*="note-editor"]',
                'div[data-contents="true"]',
                'section[contenteditable="true"]'
            ];

            function getTitleInfo() {
                if (isVisible(titleEl)) {
                    return { node: titleEl, rect: titleEl.getBoundingClientRect() };
                }
                const selectors = [
                    'input[placeholder*="标题"]',
                    'textarea[placeholder*="标题"]',
                    'input[type="text"]'
                ];
                for (const sel of selectors) {
                    const nodes = Array.from(document.querySelectorAll(sel));
                    for (const node of nodes) {
                        if (isVisible(node)) {
                            return { node, rect: node.getBoundingClientRect() };
                        }
                    }
                }
                return { node: null, rect: null };
            }

            const titleInfo = getTitleInfo();
            const titleRect = titleInfo.rect;

            function scoreByTitle(rect) {
                if (!titleRect) return 0;
                if (rect.top < titleRect.bottom - 20) {
                    return -1000;
                }
                const gap = Math.max(0, rect.top - titleRect.bottom);
                return Math.max(0, 2000 - gap * 2);
            }

            for (const sel of prioritySelectors) {
                const nodes = Array.from(document.querySelectorAll(sel));
                for (const node of nodes) {
                    if (!isVisible(node)) continue;
                    if (titleInfo.node && node === titleInfo.node) continue;
                    const rect = node.getBoundingClientRect();
                    if (scoreByTitle(rect) < 0) continue;
                    return node;
                }
            }

            const contentCandidates = [];
            const editableNodes = Array.from(document.querySelectorAll('[contenteditable="true"], div[role="textbox"], div[tabindex="0"]'));
            editableNodes.forEach(node => {
                if (!isVisible(node)) return;
                if (titleInfo.node && node === titleInfo.node) return;
                const rect = node.getBoundingClientRect();
                const text = (node.innerText || '').trim();
                let score = rect.width * rect.height;
                if (rect.height > 220) score += 2500;
                if (rect.height > 120) score += 1500;
                if (rect.height > 80) score += 800;
                score += scoreByTitle(rect);
                if (!text) score += 500; // Prefer empty editors
                contentCandidates.push({ node, score });
            });

            const textareaNodes = Array.from(document.querySelectorAll('textarea'));
            textareaNodes.forEach(node => {
                if (!isVisible(node)) return;
                if (titleInfo.node && node === titleInfo.node) return;
                const rect = node.getBoundingClientRect();
                let score = rect.width * rect.height;
                if (/内容|正文|describe|desc/i.test(node.placeholder || '')) {
                    score += 1500;
                }
                score += scoreByTitle(rect);
                contentCandidates.push({ node, score });
            });

            if (titleInfo.node) {
                let parent = titleInfo.node.parentElement;
                let depth = 0;
                while (parent && depth < 5) {
                    const siblings = Array.from(parent.querySelectorAll('[contenteditable="true"], div[role="textbox"], textarea'));
                    siblings.forEach(node => {
                        if (!isVisible(node)) return;
                        if (node === titleInfo.node) return;
                        const rect = node.getBoundingClientRect();
                        let score = rect.width * rect.height + 500;
                        score += scoreByTitle(rect);
                        contentCandidates.push({ node, score });
                    });
                    parent = parent.parentElement;
                    depth += 1;
                }
            }

            if (contentCandidates.length === 0) {
                return null;
            }

            contentCandidates.sort((a, b) => b.score - a.score);
            return contentCandidates[0].node;
        """
        try:
            return self.driver.execute_script(script, title_element)
        except Exception as err:
            logger.debug(f"定位内容区域失败: {err}")
            return None

    def _fill_content_area(self, element, text: str) -> bool:
        """根据元素类型填写内容"""
        if not element:
            return False
        try:
            self.driver.execute_script("""
                const el = arguments[0];
                const value = arguments[1];
                function trigger(target) {
                    ['focus','click','input','change','blur','keyup','keydown'].forEach(evt => {
                        target.dispatchEvent(new Event(evt, { bubbles: true }));
                    });
                }
                if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                    el.focus();
                    el.value = value;
                    trigger(el);
                } else {
                    el.focus();
                    el.click();
                    el.innerHTML = '';
                    value.split('\\\\n').forEach(line => {
                        const p = document.createElement('p');
                        if (line.trim() === '') {
                            p.innerHTML = '<br />';
                        } else {
                            p.textContent = line;
                        }
                        el.appendChild(p);
                    });
                    trigger(el);
                }
            """, element, text)
            return True
        except Exception as err:
            logger.warning(f"内容写入失败: {err}")
            return False

    def _detect_publish_result(self) -> Optional[str]:
        """通过页面内容或 URL 判断发布结果"""
        self._switch_to_latest_window()
        try:
            current_url = self.driver.current_url
        except Exception:
            current_url = ""

        if "/explore/" in current_url:
            note_id = current_url.split('/explore/')[-1].split('?')[0]
            logger.info(f"📝 检测到 explore 页面，笔记 ID: {note_id}")
            return note_id
        if "user/profile" in current_url:
            logger.info("检测到跳转到个人主页，可能已发布成功")
            return f"published_{int(time.time())}"

        try:
            body_text = self.driver.execute_script(
                "return document.body ? document.body.innerText : ''"
            ) or ""
            for keyword in self.SUCCESS_KEYWORDS:
                if keyword in body_text:
                    logger.info(f"检测到页面提示『{keyword}』，推测发布已提交")
                    return f"submitted_{int(time.time())}"
        except Exception as detect_err:
            logger.debug(f"解析发布结果失败: {detect_err}")

        return None
    
    def publish_note(
        self,
        title: str,
        content: str,
        images: List[str] = None,
        tags: List[str] = None,
        is_private: bool = False
    ) -> Optional[str]:
        """
        发布笔记到小红书
        
        Args:
            title: 标题
            content: 内容
            images: 图片路径列表
            tags: 标签列表
            is_private: 是否私密
            
        Returns:
            笔记 ID（如果成功）
        """
        try:
            self._init_driver()
            logger.info(f"开始发布笔记: {title}")
            
            # 等待页面稳定
            self._pause(self.BASE_DELAY)
            
            # 提示用户
            logger.warning("=" * 60)
            logger.warning("⚠️  当前版本需要手动配合操作")
            logger.warning("请按照以下步骤操作：")
            logger.warning("1. 浏览器将打开小红书页面")
            logger.warning("2. 请手动点击「发布笔记」按钮")
            logger.warning("3. 上传图片（如果需要）")
            logger.warning("4. 程序会自动填写标题和内容")
            logger.warning("5. 请手动点击「发布」按钮")
            logger.warning("=" * 60)
            
            # 1. 直接打开图文发布页面
            logger.info("步骤 1/8: 打开小红书图文发布页面...")
            self.driver.get('https://creator.xiaohongshu.com/publish/publish?source=official&from=tab_switch')

            if not self._wait_for_editor_ready():
                logger.error("未能进入图文编辑器，请手动确认后重试")
                return None

            # 某些账号需要先点击“新的创作/图文笔记”按钮
            self._enter_new_creation_flow()
            
            # 等待页面加载
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.querySelector('#app') && document.querySelector('#app').children.length > 0")
                )
                logger.info("✅ 页面已加载")
            except:
                logger.warning("⚠️ 页面加载超时")
            
            # 等待编辑器渲染
            self._pause(self.LONG_DELAY)
            logger.info(f"当前 URL: {self.driver.current_url}")
            
            # 调试：打印页面结构
            page_info = self.driver.execute_script("""
                return {
                    title: document.title,
                    bodyText: document.body.innerText.substring(0, 200),
                    inputCount: document.querySelectorAll('input').length,
                    textareaCount: document.querySelectorAll('textarea').length,
                    editableCount: document.querySelectorAll('[contenteditable]').length,
                    allInputs: Array.from(document.querySelectorAll('input')).map(i => ({
                        type: i.type,
                        placeholder: i.placeholder,
                        id: i.id,
                        className: i.className.substring(0, 30)
                    }))
                };
            """)
            logger.info(f"页面信息: title='{page_info['title']}' inputs={page_info['inputCount']} textareas={page_info['textareaCount']} editables={page_info['editableCount']}")
            if page_info['allInputs']:
                logger.info(f"所有输入框: {page_info['allInputs']}")
            
            # 2. 等待并查找标题输入框
            logger.info("步骤 2/8: 查找标题输入框...")
            self._pause()
            
            # 使用 JavaScript 查找所有输入框并打印信息
            inputs_info = self.driver.execute_script("""
                var inputs = document.querySelectorAll('input[type="text"]');
                return Array.from(inputs).map(function(input, index) {
                    return {
                        index: index,
                        placeholder: input.placeholder || '',
                        visible: input.offsetParent !== null
                    };
                });
            """)
            
            logger.info(f"找到 {len(inputs_info)} 个 input[type='text'] 输入框")
            
            # 尝试查找任何类型的输入框
            title_input = self.driver.execute_script("""
                // 尝试多种选择器
                var selectors = [
                    'input[type="text"]',
                    'input[placeholder*="标题"]',
                    'input[placeholder*="title"]',
                    'textarea[placeholder*="标题"]',
                    '[contenteditable="true"]'
                ];
                
                for (var i = 0; i < selectors.length; i++) {
                    var elements = document.querySelectorAll(selectors[i]);
                    for (var j = 0; j < elements.length; j++) {
                        if (elements[j].offsetParent !== null) {
                            console.log('找到输入元素:', selectors[i]);
                            return elements[j];
                        }
                    }
                }
                return null;
            """)
            
            if title_input:
                logger.info("✅ 找到标题输入框")
            else:
                logger.error("❌ 未找到标题输入框")
                # 保存截图用于调试
                try:
                    screenshot_path = f"/Users/w0r1d/Desktop/agent/output/debug_screenshot_{int(time.time())}.png"
                    self.driver.save_screenshot(screenshot_path)
                    logger.info(f"已保存调试截图: {screenshot_path}")
                except:
                    pass
            
            # 3. 填写标题
            if title_input:
                logger.info("步骤 3/8: 填写标题...")
                try:
                    # 使用 JavaScript 直接设置并触发事件
                    self.driver.execute_script("""
                        arguments[0].focus();
                        arguments[0].value = arguments[1];
                        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                        arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                    """, title_input, title)
                    self._pause(1)
                    logger.info(f"✅ 标题已填写: {title[:20]}...")
                except Exception as e:
                    logger.error(f"标题填写失败: {e}")
            else:
                logger.error("❌ 未找到标题输入框，无法填写标题")
            
            self._pause()
            
            # 4. 填写内容
            logger.info("步骤 4/8: 填写内容...")
            content_filled = False
            
            # 完整内容（包含标签）
            full_content = content
            if tags:
                full_content += "\n\n" + " ".join([f"#{tag}" for tag in tags])
            
            # 使用 JavaScript 查找所有可编辑区域
            try:
                self._pause(self.BASE_DELAY)  # 等待内容区域加载

                content_area = self._find_content_area(title_input)
                if content_area:
                    logger.info("优先策略找到内容区域，尝试填充...")
                    if self._fill_content_area(content_area, full_content):
                        logger.info(f"✅ 内容已填写 ({len(full_content)} 字符)")
                        content_filled = True
                        self._pause(1.5)
                    else:
                        logger.warning("优先策略填充失败，将尝试兼容模式")
                else:
                    logger.info("优先策略未定位内容区域，尝试兼容模式")
                
                # 查找所有 contenteditable 元素
                editable_info = self.driver.execute_script("""
                    var editables = document.querySelectorAll('[contenteditable="true"], div[role="textbox"], textarea');
                    return Array.from(editables).map(function(el, index) {
                        var rect = el.getBoundingClientRect();
                        return {
                            index: index,
                            tagName: el.tagName,
                            visible: el.offsetParent !== null,
                            width: rect.width,
                            height: rect.height,
                            text: (el.innerText || el.value || '').substring(0, 20)
                        };
                    });
                """)
                
                logger.info(f"找到 {len(editable_info)} 个可编辑元素:")
                for info in editable_info:
                    logger.info(f"  [{info['index']}] {info['tagName']} {info['width']:.0f}x{info['height']:.0f} visible={info['visible']} text='{info['text']}'")
                
                # 获取所有可见的 contenteditable 元素
                editable_elements = self.driver.execute_script("""
                    var titleEl = arguments[0];
                    var editables = document.querySelectorAll('[contenteditable="true"], div[role="textbox"], textarea');
                    return Array.from(editables).filter(function(el) {
                        if (titleEl && el === titleEl) return false;
                        if (el.offsetParent === null) return false;
                        var rect = el.getBoundingClientRect();
                        return rect.height > 24 && rect.width > 200;
                    });
                """, title_input)
                
                # 选择最大的可编辑区域作为内容区域（排除第一个，通常是标题）
                if not content_filled:
                    if len(editable_elements) > 0:
                        fallback_area = editable_elements[-1]
                        if self._fill_content_area(fallback_area, full_content):
                            logger.info(f"✅ 兼容模式成功填写内容 ({len(full_content)} 字符)")
                            content_filled = True
                            self._pause(1)
                        else:
                            logger.warning("兼容模式填充失败")
                    else:
                        logger.warning(f"可编辑元素不足 (共 {len(editable_elements)} 个)")
                
                if not content_filled and title_input:
                    try:
                        logger.info("尝试使用标题相对定位的键盘输入方式...")
                        self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", title_input)
                        actions = ActionChains(self.driver)
                        actions.move_to_element(title_input).move_by_offset(0, 160).click().pause(0.5).send_keys(full_content).perform()
                        content_filled = True
                        logger.info(f"✅ 相对定位方式成功输入内容 ({len(full_content)} 字符)")
                        self._pause(1)
                    except Exception as typing_err:
                        logger.warning(f"相对定位输入失败: {typing_err}")
                    
            except Exception as e:
                logger.warning(f"内容填写失败: {e}")
            
            if not content_filled:
                logger.warning("⚠️  未能自动填写内容")
                logger.info(f"\n内容预览:\n{full_content}\n")
            
            self._pause()

            if content_filled:
                api_note_id = self._publish_via_long_text_api(title, full_content, tags)
                if api_note_id:
                    return api_note_id
            
            # 5. 点击一键排版进入预览
            logger.info("步骤 5/8: 点击『一键排版』按钮进入预览...")
            layout_clicked = False
            if content_filled:
                layout_clicked = self._click_button_with_texts(self.LAYOUT_BUTTON_TEXTS, "一键排版", timeout=100)
                if layout_clicked:
                    logger.info("✅ 已触发『一键排版』，等待预览页面加载...")
                    self._pause(self.LONG_DELAY * 2)
                else:
                    logger.warning("⚠️ 未能自动定位『一键排版』按钮，请检查页面或手动点击一次")
            else:
                logger.warning("⚠️ 内容未自动填写，暂不尝试自动点击『一键排版』")

            # 6. 预览页点击下一步
            logger.info("步骤 6/8: 在预览页点击『下一步』...")
            preview_next_clicked = False
            if content_filled:
                self._pause(self.LONG_DELAY)
                preview_next_clicked = self._click_button_with_texts(
                    self.PREVIEW_NEXT_BUTTON_TEXTS,
                    "下一步",
                    timeout=100
                )
                if not preview_next_clicked:
                    self._pause(self.BASE_DELAY)
                    preview_next_clicked = self._click_by_xpath([
                        "//button[contains(.,'下一步')]",
                        "//span[contains(.,'下一步')]/ancestor::button[1]",
                        "//div[@role='button' and contains(.,'下一步')]",
                        "//button[contains(@class,'next') and contains(@class,'btn')]"
                    ], "下一步(备用)", timeout=45)
                if preview_next_clicked:
                    logger.info("✅ 预览页『下一步』已点击，准备出现『发布』按钮")
                    self._pause(self.BASE_DELAY)
                    self._wait_for_final_publish_view(timeout=120)
                    self._scroll_to_bottom(repeat=2)
                else:
                    self._pause(self.BASE_DELAY)
                    logger.warning("⚠️ 未能自动点击『下一步』，请在预览页手动点击以继续")
            else:
                logger.warning("⚠️ 内容尚未自动填写，需手动完成预览步骤")
            
            # 7. 查找发布按钮
            logger.info("步骤 7/8: 查找发布按钮...")
            try:
                publish_clicked = False
                if content_filled and preview_next_clicked:
                    self._scroll_to_bottom(repeat=2)
                    publish_clicked = self._click_button_with_texts(
                        self.PUBLISH_BUTTON_TEXTS,
                        "发布",
                        timeout=45
                    )
                    if not publish_clicked:
                        publish_clicked = self._click_by_xpath([
                            "//button[contains(.,'发布')]",
                            "//span[contains(.,'发布')]/ancestor::button[1]",
                            "//div[@role='button' and contains(.,'发布')]"
                        ], "发布(备用)", timeout=30)

                if publish_clicked:
                    logger.info("✅ 已自动点击『发布』按钮，等待结果...")
                    time.sleep(3)
                else:
                    if not content_filled:
                        logger.warning("⚠️  内容未自动填写，需要手动操作")
                    elif not preview_next_clicked:
                        logger.warning("⚠️  未完成预览页『下一步』，请手动点击后再发布")
                    else:
                        logger.warning("⚠️  未找到发布按钮，需要手动点击")

                    logger.warning("\n👉 请手动操作：")
                    logger.warning("   1. 检查标题和内容是否正确")
                    if not content_filled:
                        logger.warning("   2. 手动填写内容")
                        logger.warning("   3. 点击『一键排版』→『下一步』进入预览")
                        logger.warning("   4. 点击『发布』按钮")
                    else:
                        logger.warning("   2. 点击『一键排版』→『下一步』")
                        logger.warning("   3. 点击『发布』按钮")
                    logger.warning("\n⏳ 等待 10 秒...")

                    for i in range(10, 0, -1):
                        print(f"\r   倒计时: {i} 秒   ", end='', flush=True)
                        time.sleep(1)
                    print("\n")
                    
            except Exception as e:
                logger.warning(f"查找发布按钮失败: {e}")
            
            # 8. 尝试获取发布结果
            logger.info("步骤 8/8: 检查发布结果...")
            publish_result = self._detect_publish_result()
            if publish_result:
                return publish_result

            logger.warning("⚠️  未检测到明确的页面跳转或成功提示")
            logger.info("如果已成功发布，可以忽略此警告；否则请检查浏览器状态")
            return f"manual_{int(time.time())}"
            
        except Exception as e:
            logger.error(f"发布过程出错: {e}")
            # 保存截图用于调试
            if self.driver:
                screenshot_path = f"error_screenshot_{int(time.time())}.png"
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"错误截图已保存: {screenshot_path}")
            return None
    
    def _force_close(self):
        if not self.driver:
            self._close_pending = False
            return
        try:
            self.driver.quit()
            logger.info("浏览器已关闭")
        except Exception as err:
            logger.debug(f"关闭浏览器时出错: {err}")
        finally:
            self.driver = None
            self._close_pending = False

    def _delayed_close(self, wait_seconds: int):
        try:
            deadline = time.time() + max(wait_seconds, 0)
            while time.time() < deadline:
                if not self.driver:
                    self._close_pending = False
                    return
                try:
                    handles = self.driver.window_handles
                    if not handles:
                        logger.info("检测到浏览器窗口已手动关闭")
                        self._force_close()
                        return
                except Exception:
                    break
                time.sleep(3)
            if self.driver:
                logger.info("超过等待时间，自动关闭浏览器")
                self._force_close()
        finally:
            self._close_thread = None

    def close(self, wait_before_close: int = 120):
        """关闭浏览器（支持延迟，方便手动查看）"""
        if not self.driver:
            return
        if self._close_pending:
            logger.debug("浏览器关闭已在排队")
            return
        if wait_before_close <= 0:
            self._force_close()
            return

        self._close_pending = True
        logger.info(f"浏览器保持打开，可手动关闭；{wait_before_close} 秒后将自动关闭")
        self._close_thread = threading.Thread(
            target=self._delayed_close,
            args=(wait_before_close,),
            daemon=True
        )
        self._close_thread.start()
    
    def __del__(self):
        """析构函数，确保浏览器关闭"""
        self.close()


# 示例用法
if __name__ == "__main__":
    from config import settings
    
    publisher = XiaohongshuSeleniumPublisher(cookie=settings.XIAOHONGSHU_COOKIE)
    
    try:
        note_id = publisher.publish_note(
            title="测试发布",
            content="这是一条通过自动化工具发布的测试笔记 📝",
            tags=["测试", "自动化"]
        )
        
        if note_id:
            print(f"✅ 发布成功！笔记 ID: {note_id}")
        else:
            print("❌ 发布失败")
    finally:
        publisher.close()
