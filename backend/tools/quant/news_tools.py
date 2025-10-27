import logging
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from services.service_factory import get_news_service


class NewsInput(BaseModel):
    """Input for news search"""
    query: str = Field(description="Search query for news articles (e.g., 'AAPL', 'Tesla')")
    max_articles: int = Field(default=10, description="Maximum number of articles to return")
    from_date: str = Field(default=None, description="The start date to fetch the news from would be at least 7 days prior the inputted date_of_trade. If input date_of_trade is not provided, use 7 days prior the current date. (in ISO 8601 format)")
    to_date: str = Field(default=None, description="The end date to fetch the news from would be the inputted date_of_trade. If input date_of_trade is not provided, use the current date. (in ISO 8601 format)")


@tool("get_news_articles", args_schema=NewsInput)
def get_news_articles(query: str, max_articles: int = 10, from_date: str = None, to_date: str = None) -> str:
    """Get recent news articles about stocks, companies, or financial topics"""
    try:
        logger.info(f"⚒️ Fetching news articles for {query} from {from_date} to {to_date}")
        
        news_service = get_news_service()
        articles = news_service.get_top_articles_summary(
            query=query,
            max_articles=max_articles,
            from_date=from_date,
            to_date=to_date,
            query_type="news"
        )
        
        if not articles:
            return f"No news articles found for: {query}"
        
        result = f"Recent news for '{query}':\n\n"
        
        for i, article in enumerate(articles, 1):
            title = article.get('title', 'No title')
            content = article.get('content', 'No content')
            
            result += f"{i}. {title}\n"
            result += f"   {content}\n\n"
        
        return result
        
    except Exception as e:
        return f"Error getting news: {str(e)}"