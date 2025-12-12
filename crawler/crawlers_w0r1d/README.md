# Crawlers 模块说明

`crawlers/` 目录包含数据采集组件，用于为多智能体工作流提供结构化内容。目前包含：

- `arxiv_crawler.py`：抓取最新 arXiv 论文。
- `news_crawler.py`：从 NewsAPI 或 RSS 源获取新闻。

## 依赖

在项目根目录执行：

```bash
pip install -r requirements.txt
```

额外说明：

- `arxiv_crawler` 依赖 `arxiv` 官方 Python SDK。
- `news_crawler` 默认使用 `requests`、`feedparser` 与 `beautifulsoup4`。

## ArxivCrawler

主要接口：

- `crawl_papers(query: str, max_results: int, days: int)`：按关键词与时间窗口抓取最新论文。
- `get_paper_by_id(arxiv_id: str)`：通过 ID 获取单篇元数据。

返回的数据字段包含标题、作者列表、摘要、发布时间、PDF 链接、分类等，可直接交给生成器或发布器。

使用示例：

```python
from crawlers.arxiv_crawler import ArxivCrawler

crawler = ArxivCrawler()
papers = crawler.crawl_papers(query="large language model", max_results=5, days=3)
for paper in papers:
    print(paper["title"], paper["pdf_url"])
```

## NewsCrawler

支持两种来源：

1. **NewsAPI**：需要在 `.env` 配置 `NEWS_API_KEY`；调用 `crawl_news_api(query="AI", days=2)` 即可获取近几天的英文新闻。
2. **RSS 源**：调用 `crawl_rss_feed(feed_url)`，内部使用 `feedparser` 解析并返回统一字段。

当未配置 API key 时，会自动回退至 `_get_sample_news()`，便于开发环境调试。

示例：

```python
from crawlers.news_crawler import NewsCrawler
from config import settings

crawler = NewsCrawler(api_key=settings.NEWS_API_KEY)
news = crawler.crawl_news_api(query="robotics", days=1)
for item in news:
    print(item["title"], item["url"])
```

## 目录结构

```
crawlers/
├── README.md             # 本文件
├── __init__.py           # 导出 crawler 类
├── arxiv_crawler.py
└── news_crawler.py
```

## 扩展建议

- 新增站点时，可参考现有类的接口签名（统一返回 `List[Dict]`）。
- 如果需要调度代理/重试，可在各 crawler 内部统一使用 `requests.Session()` 并添加自定义 headers。
- 建议把新 crawler 的配置项加入 `.env` 与 `config/settings.py`，保持调用方式一致。
