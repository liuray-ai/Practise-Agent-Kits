"""
arXiv paper crawler - crawls latest papers from arXiv
"""
import arxiv
from typing import List, Dict
from datetime import datetime, timedelta
from utils import get_logger

logger = get_logger("ArxivCrawler")


class ArxivCrawler:
    """Crawler for arXiv papers"""
    
    def __init__(self):
        self.client = arxiv.Client()
    
    def crawl_papers(
        self,
        query: str = "medical imaging",
        max_results: int = 10,
        days: int = 7
    ) -> List[Dict]:
        """
        Crawl papers from arXiv
        
        Args:
            query: Search query (e.g., "medical imaging", "computer vision")
            max_results: Maximum number of papers to return
            days: Number of days back to search
            
        Returns:
            List of paper metadata
        """
        try:
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # Build search query
            search_query = f"{query} AND submittedDate:[{start_date.strftime('%Y%m%d')}* TO {end_date.strftime('%Y%m%d')}*]"
            
            # Search arXiv
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending
            )
            
            papers = []
            for result in self.client.results(search):
                papers.append({
                    "title": result.title,
                    "authors": [author.name for author in result.authors],
                    "summary": result.summary,
                    "published": result.published.isoformat(),
                    "updated": result.updated.isoformat(),
                    "pdf_url": result.pdf_url,
                    "categories": result.categories,
                    "primary_category": result.primary_category,
                    "arxiv_id": result.entry_id.split("/")[-1]
                })
            
            logger.info(f"Crawled {len(papers)} papers from arXiv")
            return papers
            
        except Exception as e:
            logger.error(f"Failed to crawl arXiv papers: {e}")
            return []
    
    def get_paper_by_id(self, arxiv_id: str) -> Dict:
        """
        Get a specific paper by arXiv ID
        
        Args:
            arxiv_id: arXiv paper ID (e.g., "2301.00001")
            
        Returns:
            Paper metadata
        """
        try:
            search = arxiv.Search(id_list=[arxiv_id])
            result = next(self.client.results(search))
            
            return {
                "title": result.title,
                "authors": [author.name for author in result.authors],
                "summary": result.summary,
                "published": result.published.isoformat(),
                "updated": result.updated.isoformat(),
                "pdf_url": result.pdf_url,
                "categories": result.categories,
                "primary_category": result.primary_category,
                "arxiv_id": result.entry_id.split("/")[-1]
            }
            
        except Exception as e:
            logger.error(f"Failed to get paper {arxiv_id}: {e}")
            return {}
