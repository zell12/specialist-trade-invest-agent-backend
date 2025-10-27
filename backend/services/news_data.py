import requests
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from .cache_service import get_cache_service
    CACHING_ENABLED = True
    logger.info("Cache service imported successfully")
except ImportError as e:
    logger.warning(f"Caching service not available - running without cache: {e}")
    CACHING_ENABLED = False

class NewsDataService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_base_url = "https://newsapi.org/v2"
        self.api_key = api_key or os.getenv("NEWS_API_KEY")
        self.headers = {"User-Agent": "Trading-Investing-Agent-Py"}
        
        try:
            self.cache = get_cache_service() if CACHING_ENABLED else None
            if self.cache:
                logger.info("News service initialized with caching enabled")
            else:
                logger.warning("News service initialized without caching")
        except Exception as e:
            logger.error(f"Failed to initialize cache service: {e}")
            self.cache = None
        self.service_name = "news_service"
    
    def _get_cached_or_execute(self, method_name: str, params: Dict[str, Any], 
                              execute_func, query_type: str = ""):
        """Generic caching wrapper for news service methods"""
        if not self.cache:
            return execute_func()
        
        cached_result, is_hit = self.cache.get(
            self.service_name, method_name, params, query_type
        )
        
        if is_hit:
            logger.info(f"✓ Cache HIT for {method_name}: {params.get('query', 'N/A')}")
            return cached_result
        
        try:
            logger.info(f"⚡ Executing {method_name}: {params.get('query', 'N/A')}")
            result = execute_func()
            
            self.cache.set(self.service_name, method_name, params, result, query_type)
            logger.info(f"✓ Cached result for {method_name}")
            
            return result
            
        except Exception as e:
            logger.error(f"✗ Error in {method_name}: {str(e)}")
            raise
    
    def _make_request(self, endpoint: str, params: Dict[str, Any], operation_name: str) -> Dict[str, Any]:
        """Execute HTTP requests with error handling"""
        url = f"{self.api_base_url}/{endpoint}"
        
        try:
            logger.info(f"Executing Request: {url}")
            
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            
            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.warning(f"Error Response ({response.status_code}): {response.text}")
            else:
                logger.info(f"✅ Success Response: Request completed")
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"{operation_name} - ended. Found {result.get('totalResults', 0)} articles")
            return result
            
        except requests.RequestException as e:
            error_msg = f"Error encountered: {str(e)}"
            
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    if 'message' in error_data:
                        error_msg = f"NewsAPI Error: {error_data['message']}"
                    elif 'error' in error_data:
                        error_msg = f"NewsAPI Error: {error_data['error']}"
                except (json.JSONDecodeError, ValueError):
                    error_msg = f"NewsAPI Error ({e.response.status_code}): {e.response.text}"
            
            logger.error(error_msg)
            raise Exception(error_msg)
    
    def get_everything_news(
        self, 
        query: str, 
        from_date: Optional[str] = None, 
        to_date: Optional[str] = None,
        page_size: int = 20,
        query_type: str = "news"
    ) -> Dict[str, Any]:
        """Get news articles from NewsAPI everything endpoint"""
        logger.info(f"Get Everything News - started for query: {query}")
        
        def execute_request():
            nonlocal from_date, to_date
            if not from_date:
                from_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            if not to_date:
                to_date = datetime.now().strftime("%Y-%m-%d")
            
            params = {
                "q": query,
                "from": from_date,
                "to": to_date,
                "sortBy": "publishedAt",
                "apiKey": self.api_key,
                "pageSize": min(page_size, 100)
            }
            
            return self._make_request("everything", params, "Get Everything News")
        
        cache_params = {
            "query": query,
            "from_date": from_date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
            "to_date": to_date or datetime.now().strftime("%Y-%m-%d"),
            "page_size": page_size
        }
        
        return self._get_cached_or_execute("get_everything_news", cache_params, execute_request, query_type)
    
    def get_top_headlines(
        self, 
        query: Optional[str] = None,
        country: str = "us",
        category: Optional[str] = None,
        page_size: int = 20,
        query_type: str = "headlines"
    ) -> Dict[str, Any]:
        """
        Get top headlines from NewsAPI.org
        
        Args:
            query: Search query (optional)
            country: Country code (default: "us")
            category: Category (business, entertainment, general, health, science, sports, technology)
            page_size: Number of articles to return (max 100, default 20)
            query_type: Context for caching (headlines, breaking, market)
            
        Returns:
            Top headlines data as dictionary
        """
        logger.info(f"Get Top Headlines - started")
        
        def execute_request():
            # Build parameters
            params = {
                "apiKey": self.api_key,
                "pageSize": min(page_size, 100)
            }
            
            if query:
                params["q"] = query
            if country:
                params["country"] = country
            if category:
                params["category"] = category
            
            return self._make_request("top-headlines", params, "Get Top Headlines")
        
        # Use caching wrapper
        cache_params = {
            "query": query,
            "country": country,
            "category": category,
            "page_size": page_size
        }
        
        return self._get_cached_or_execute("get_top_headlines", cache_params, execute_request, query_type)
    
    def get_top_articles_summary(
        self, 
        query: str, 
        from_date: Optional[str] = None, 
        to_date: Optional[str] = None,
        max_articles: int = 10,
        query_type: str = "summary"
    ) -> list[Dict[str, str]]:
        """
        Get simplified summary of top articles with just title and content
        
        Args:
            query: Search query (e.g., "AAPL", "Tesla", "stock market")
            from_date: Start date in YYYY-MM-DD format (defaults to yesterday)
            to_date: End date in YYYY-MM-DD format (defaults to today)
            max_articles: Maximum number of articles to return (default: 10)
            query_type: Context for caching (summary, analysis, brief)
            
        Returns:
            List of dictionaries with 'title' and 'content' keys
        """
        def execute_request():
            # Get the full news data
            news_data = self.get_everything_news(query, from_date, to_date, page_size=max_articles, query_type=query_type)
            
            # Extract just title and content from articles
            articles_summary = []
            articles = news_data.get('articles', [])
            
            for article in articles[:max_articles]:  # Limit to max_articles
                summary = {
                    'title': article.get('title', 'No title available'),
                    'content': article.get('content', article.get('description', 'No content available'))
                }
                articles_summary.append(summary)
            
            logger.info(f"Extracted {len(articles_summary)} article summaries")
            return articles_summary
        
        # Use caching wrapper
        cache_params = {
            "query": query,
            "from_date": from_date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
            "to_date": to_date or datetime.now().strftime("%Y-%m-%d"),
            "max_articles": max_articles
        }
        
        return self._get_cached_or_execute("get_top_articles_summary", cache_params, execute_request, query_type)
    
    def invalidate_cache(self, query: str = None) -> int:
        """Invalidate cached news data"""
        if not self.cache:
            return 0
        
        if query:
            count = 0
            count += self.cache.invalidate_service(self.service_name)
            logger.info(f"Invalidated news cache for query: {query}")
            return count
        else:
            return self.cache.invalidate_service(self.service_name)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        if not self.cache:
            return {"caching": "disabled"}
        return self.cache.get_cache_stats()
    
    def clear_cache(self) -> None:
        """Clear all news cache entries"""
        if self.cache:
            self.cache.invalidate_service(self.service_name)
            logger.info("News service cache cleared")


# Example usage
if __name__ == "__main__":
    service = NewsDataService()
    
    try:
        articles = service.get_top_articles_summary("AAPL OR Apple stock", max_articles=10)
        print(f"Found {len(articles)} articles about Apple:")
        for i, article in enumerate(articles, 1):
            print(f"\n{i}. {article['title']}")
            print(f"   Content: {article['content'][:150]}...")
    except Exception as e:
        print(f"Error: {e}")
    
    try:
        headlines = service.get_top_headlines(category="business")
        print(f"Found {headlines.get('totalResults', 0)} business headlines")
    except Exception as e:
        print(f"Error: {e}")