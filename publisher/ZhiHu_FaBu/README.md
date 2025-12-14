# **知乎自动发布助手**

## **项目简介**

本项目是一个基于 Python 和 Selenium 的自动化工具，用于连接 MySQL 数据库，读取当日爬取的文章内容，并自动发布到知乎平台。

程序通过接管本地已开启调试端口的 Chrome 浏览器运行。通过指定用户数据目录（User Data Dir），程序可以保存首次登录的 Cookie 和 Session。这意味着用户只需在第一次运行时手动扫码登录，后续运行即可实现免登录自动发布。

## **环境依赖**

* Python 3.8+  
* Google Chrome 浏览器  
* ChromeDriver (需与浏览器版本匹配，项目内附带了一个 windows 版)

## **安装步骤**

1. **安装 Python 依赖**  
   在项目根目录下运行以下命令：  
   pip install \-r requirements.txt

2. **配置数据库**  
   打开 zhihu\_db\_publisher.py，修改 DB\_CONFIG 字典中的数据库连接信息：  
   DB\_CONFIG \= {  
       'host': '127.0.0.1',  
       'port': 3306,  
       'user': 'root',  
       'password': 'your\_password',  
       'database': 'your\_database',  
       'charset': 'utf8mb4'  
   }

   注意：数据库表结构需要包含 id, title, content, time 等基础字段。

## **运行流程**

本项目采用接管现有浏览器的方式，请严格按照以下顺序操作，以实现登录状态的保存和复用。

### **第一步：创建用户数据文件夹**

在电脑的一个固定位置创建一个文件夹，用于存放 Chrome 的用户数据（如登录信息、缓存等）。  
例如：D:\\zhihu\_user\_data

### **第二步：启动 Chrome 调试模式**

必须通过命令行启动 Chrome，指定远程调试端口和用户数据目录。

Windows 启动命令示例：  
（请根据你实际的 Chrome 安装路径和第一步创建的文件夹路径修改）  
"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" \--remote-debugging-port=9222 \--user-data-dir="D:\\zhihu\_user\_data"

**Mac 启动命令示例：**

/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \--remote-debugging-port=9222 \--user-data-dir="/Users/你的用户名/zhihu\_user\_data"

### **第三步：首次运行与登录（仅第一次需要）**

1. 执行上述命令后，会打开一个干净的 Chrome 浏览器窗口。  
2. 在该窗口中手动输入知乎网址 www.zhihu.com。  
3. **手动扫码或密码登录**你的知乎账号。  
4. 登录成功后，你的登录状态会被自动保存到 D:\\zhihu\_user\_data 文件夹中。  
5. **不要关闭**这个浏览器窗口。

### **第四步：运行自动化程序**

在命令行或 IDE 中运行主程序：

python zhihu\_db\_publisher.py

程序会自动连接到刚才打开的浏览器窗口。

* **如果是首次运行**：程序接管浏览器后，你可以观察控制台输出。  
* **如果是后续运行**：  
  1. 确保按照第二步的命令启动了 Chrome（无需再次登录，因为数据已保存在 zhihu\_user\_data 中）。  
  2. 直接运行 python 脚本。  
  3. 脚本会自动读取数据库当日数据，并直接进入发布流程，无需人工干预。

## **功能特性**

1. **自动读取**：脚本根据 CURDATE() 自动筛选数据库中当天的文章。  
2. **状态保存**：利用 Chrome 的 user-data-dir 特性，一次登录，长期有效。  
3. **频率控制**：每发布一篇文章后自动暂停 5 分钟，防止触发平台风控。  
4. **去重处理**：发布成功的文章 ID 会被记录在 published\_ids.txt 中，避免重复发布。

## **常见问题**

* 报错 "由于目标计算机积极拒绝，无法连接"：  
  这通常是因为没有先执行第二步（启动 Chrome 调试模式），或者端口号不是 9222。请务必先用命令行启动浏览器。  
* 登录失效：  
  如果长时间未运行，知乎的 Cookie 可能会过期。此时只需重复“第三步”，在开启的浏览器中手动刷新页面并重新登录一次即可。