import os
import time
import platform
import pymysql
import pyperclip
from datetime import date  # 用于获取今日日期
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ================= 数据库配置区域 =================
DB_CONFIG = {
    'host': '172.16.121.112',
    'port': 3306,
    'user': 'remote_weibo',
    'password': '123456',
    'database': 'ceshishuju',
    'charset': 'utf8mb4'
}


# ==============================================

class ZhihuDBPublisher:
    def __init__(self, db_config):
        self.db_config = db_config
        self.driver = None
        self.article_list = []
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.record_file = os.path.join(self.base_dir, "published_ids.txt")

    def get_published_ids(self):
        """读取本地记录，获取已发布的文章ID"""
        if not os.path.exists(self.record_file):
            return set()
        with open(self.record_file, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())

    def save_published_id(self, article_id):
        """将发布成功的ID写入本地记录"""
        with open(self.record_file, 'a', encoding='utf-8') as f:
            f.write(f"{article_id}\n")

    def fetch_daily_articles(self):
        """从数据库获取【当日】未发布的文章"""
        today = date.today()
        print(f"正在连接数据库，查找日期为 {today} 的新文章...")

        published_ids = self.get_published_ids()

        try:
            conn = pymysql.connect(**self.db_config)
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                # 只获取今日且内容不为空的数据
                sql = "SELECT * FROM reports WHERE content != '' AND DATE(created_at) = %s ORDER BY id ASC;"
                cur.execute(sql, (today,))
                results = cur.fetchall()

                new_articles = []
                if results:
                    for art in results:
                        art_id = str(art.get('id', ''))

                        if art_id and art_id not in published_ids:
                            content = art.get('content', '')
                            if not content.strip():
                                continue

                            first_line = content.strip().split('\n')[0]
                            title = first_line.replace('#', '').strip()

                            art['title'] = title
                            new_articles.append(art)

                if new_articles:
                    self.article_list = new_articles
                    print(f"✅ 成功锁定 {len(new_articles)} 篇【今日】新文章，准备发布。")
                    return True
                else:
                    print(f"⚠️ 当前没有发现新文章（或已全部发布）。")
                    return False

        except pymysql.OperationalError as e:
            print(f"数据库连接失败：{e}")
            return False
        except Exception as e:
            print(f"获取数据时发生未知错误：{e}")
            return False
        finally:
            if 'conn' in locals() and conn.open:
                conn.close()

    def start_browser(self):
        """启动浏览器并进行登录流程"""
        print("准备启动 Chrome 浏览器...")

        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")

        user_data_dir = os.path.join(self.base_dir, "zhihu_user_data")
        options.add_argument(f"--user-data-dir={user_data_dir}")
        print(f"浏览器用户配置文件路径: {user_data_dir}")

        driver_path = os.path.join(self.base_dir, "chromedriver.exe")

        service = None
        if os.path.exists(driver_path):
            print(f"使用本地驱动：{driver_path}")
            service = Service(executable_path=driver_path)
        else:
            print("未找到本地驱动，尝试自动匹配...")

        try:
            if service:
                self.driver = webdriver.Chrome(service=service, options=options)
            else:
                self.driver = webdriver.Chrome(options=options)
            self.driver.maximize_window()
        except Exception as e:
            print(f"浏览器启动失败: {e}")
            return False

        print("正在尝试直接进入创作中心...")
        self.driver.get("https://zhuanlan.zhihu.com/write")
        time.sleep(3)

        current_url = self.driver.current_url

        if "signin" in current_url or "passport" in current_url:
            print("\n" + "=" * 60)
            print("检测到当前未登录。")
            print("请在浏览器中切换到【扫码登录】并完成扫码。")
            print("登录完成后，请回到这里按下【回车键】继续。")
            print("=" * 60 + "\n")
            input("登录成功后，请按回车键 (Enter) 继续发布 >> ")
            self.driver.get("https://zhuanlan.zhihu.com/write")
            time.sleep(2)
        else:
            print("检测到已登录状态，自动跳过扫码。")

        return True

    def publish_one_article(self, article_data):
        """发布单篇文章逻辑"""
        if not self.driver:
            return

        title = article_data.get('title', '')
        content = article_data.get('content', '')
        art_id = article_data.get('id')

        if not title or not content:
            print(f"跳过 ID:{art_id}：标题或内容为空。")
            return

        print(f"正在处理文章 ID:{art_id} | 标题:{title}")

        self.driver.get("https://zhuanlan.zhihu.com/write")

        try:
            print("正在寻找标题输入框...")
            title_box = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'textarea[placeholder*="标题"]'))
            )
            title_box.clear()
            title_box.send_keys(title)
            print("标题已输入")

            print("正在粘贴正文内容...")
            pyperclip.copy(content)

            try:
                editor_div = self.driver.find_element(By.CSS_SELECTOR, '.DraftEditor-root')
            except:
                editor_div = self.driver.find_element(By.CSS_SELECTOR, 'div[contenteditable="true"]')

            editor_div.click()
            time.sleep(1)

            ctrl_key = Keys.COMMAND if platform.system() == 'Darwin' else Keys.CONTROL
            webdriver.ActionChains(self.driver).key_down(ctrl_key).send_keys('v').key_up(ctrl_key).perform()

            print("正文已粘贴")
            time.sleep(2)

            # === 自动点击 Markdown 解析确认 ===
            try:
                print("正在检测 Markdown 解析弹窗...")
                markdown_confirm_btn = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '确认并解析')]"))
                )
                self.driver.execute_script("arguments[0].click();", markdown_confirm_btn)
                print("✅ 已点击 [确认并解析]，Markdown 格式已渲染！")
                time.sleep(2)
            except TimeoutException:
                print("ℹ️ 未出现 Markdown 弹窗（或者是纯文本/HTML），跳过此步...")
            except Exception as e:
                print(f"⚠️ 点击弹窗时发生未知错误: {e}")
            # ======================================

            print("正在点击发布按钮...")
            publish_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), '发布')]")
            publish_btn.click()

            print("等待确认弹窗...")
            time.sleep(2)
            try:
                confirm_btn = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".Modal-wrapper button.Button--primary"))
                )
                confirm_btn.click()
                print("已点击确认发布！")

                self.save_published_id(art_id)

            except TimeoutException:
                print("未点到确认按钮（可能需要手动选话题）。")

        except Exception as e:
            print(f"发布本篇出错: {e}")
            import traceback
            traceback.print_exc()

    def run(self):
        print("🚀 服务已启动，将持续运行...")

        while True:
            print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始执行检查任务...")

            # 1. 尝试获取【当日】新数据
            if self.fetch_daily_articles():
                # 2. 有数据则启动浏览器
                if self.start_browser():
                    total = len(self.article_list)
                    print(f"\n开始批量发布，本次待处理共 {total} 篇\n")

                    for index, article in enumerate(self.article_list):
                        print(f"\n-------- 正在执行第 {index + 1} / {total} 篇 --------")
                        self.publish_one_article(article)

                        # 只要不是最后一条，每发完一条都休息5分钟
                        if index < total - 1:
                            print("等待 5 分钟后发布下一篇...")
                            time.sleep(300)

                    print("\n✅ 本批次任务执行完毕！")

                    if self.driver:
                        self.driver.quit()
                        self.driver = None

            # 3. 无论是发完了所有文章，还是这次没查到文章，都统一休息5分钟再进行下一次检查
            print("😴 本轮结束，休息 5 分钟后重新检查数据库...")
            time.sleep(300)


if __name__ == "__main__":
    app = ZhihuDBPublisher(DB_CONFIG)
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n程序已手动停止。")