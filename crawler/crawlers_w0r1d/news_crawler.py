"""
News crawler - crawls latest news from various sources
"""
import requests
from typing import List, Dict
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from utils import get_logger

logger = get_logger("Newscrawler")


class NewsCrawler:
    """Crawler for news articles"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.session = requests.Session()
    
    def crawl_news_api(self, query: str = "technology", days: int = 1) -> List[Dict]:
        """
        Crawl news from NewsAPI
        
        Args:
            query: Search query
            days: Number of days back to search
            
        Returns:
            List of news articles
        """
        if not self.api_key:
            logger.warning("No NewsAPI key provided, using sample data")
            return self._get_sample_news()
        
        url = "https://newsapi.org/v2/everything"
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        params = {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "apiKey": self.api_key,
            "language": "en",
            "pageSize": 10
        }
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            articles = []
            for article in data.get("articles", []):
                articles.append({
                    "title": article.get("title"),
                    "description": article.get("description"),
                    "url": article.get("url"),
                    "source": article.get("source", {}).get("name"),
                    "published_at": article.get("publishedAt"),
                    "content": article.get("content", "")
                })
            
            logger.info(f"Crawled {len(articles)} news articles")
            return articles
            
        except Exception as e:
            logger.error(f"Failed to crawl news: {e}")
            logger.warning("Falling back to sample data for testing")
            return self._get_sample_news()
    
    def crawl_rss_feed(self, feed_url: str) -> List[Dict]:
        """
        Crawl news from RSS feed
        
        Args:
            feed_url: URL of the RSS feed
            
        Returns:
            List of news articles
        """
        import feedparser
        
        try:
            feed = feedparser.parse(feed_url)
            articles = []
            
            for entry in feed.entries[:10]:
                articles.append({
                    "title": entry.get("title"),
                    "description": entry.get("summary", ""),
                    "url": entry.get("link"),
                    "source": feed.feed.get("title", "RSS"),
                    "published_at": entry.get("published", ""),
                    "content": entry.get("description", "")
                })
            
            logger.info(f"Crawled {len(articles)} articles from RSS feed")
            return articles
            
        except Exception as e:
            logger.error(f"Failed to crawl RSS feed: {e}")
            return []
    
    def _get_sample_news(self) -> List[Dict]:
        """Get sample news for testing"""
        return [
            {
                "title": "Sample Tech News: AI Breakthrough",
                "description": "Researchers announce major breakthrough in AI technology",
                "url": "https://example.com/news/1",
                "source": "Tech Daily",
                "published_at": datetime.now().isoformat(),
                "content": "Sample content about AI breakthrough..."
            },
            {
                "title": "Sample Tech News: New Framework Released",
                "description": "Popular framework releases version 2.0 with new features",
                "url": "https://example.com/news/2",
                "source": "Dev News",
                "published_at": datetime.now().isoformat(),
                "content": "Sample content about framework release..."
            }
        ]
