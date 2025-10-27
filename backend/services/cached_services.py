# Service Integration Example with Smart Caching
import functools
import json
from typing import Any, Dict, Optional
from .cache_service import get_cache_service, CacheLevel
import logging

logger = logging.getLogger(__name__)

class CachedFinanceService:
    """
    Enhanced Finance Service with intelligent caching
    Wraps the original FinanceDataService with caching capabilities
    """
    
    def __init__(self, original_service):
        self.original_service = original_service
        self.cache = get_cache_service()
        self.service_name = "finance_service"
    
    def _cache_key_params(self, method_name: str, **kwargs) -> Dict[str, Any]:
        """Extract relevant parameters for cache key generation"""
        # Remove internal parameters that shouldn't affect caching
        cache_params = {k: v for k, v in kwargs.items() 
                       if not k.startswith('_') and v is not None}
        return cache_params
    
    def _get_cached_or_execute(self, method_name: str, original_method, query_type: str = "", **kwargs):
        """Generic caching wrapper for any finance service method"""
        cache_params = self._cache_key_params(method_name, **kwargs)
        
        # Try cache first
        cached_result, is_hit = self.cache.get(
            self.service_name, method_name, cache_params, query_type
        )
        
        if is_hit:
            logger.info(f"✓ Cache HIT for {method_name}: {cache_params.get('ticker_symbol', 'N/A')}")
            return cached_result
        
        # Execute original method
        try:
            logger.info(f"⚡ Executing {method_name}: {cache_params.get('ticker_symbol', 'N/A')}")
            result = original_method(**kwargs)
            
            # Cache the result
            self.cache.set(self.service_name, method_name, cache_params, result, query_type)
            logger.info(f"✓ Cached result for {method_name}")
            
            return result
            
        except Exception as e:
            logger.error(f"✗ Error in {method_name}: {str(e)}")
            raise
    
    def get_prices(self, ticker_symbol: str, start_date: Optional[str] = None, 
                   end_date: Optional[str] = None, interval: str = "minute", 
                   interval_multiplier: int = 15, query_type: str = "trading"):
        """Cached version of get_prices"""
        return self._get_cached_or_execute(
            "get_prices", 
            self.original_service.get_prices,
            query_type,
            ticker_symbol=ticker_symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            interval_multiplier=interval_multiplier
        )
    
    def get_company_facts(self, ticker_symbol: str, query_type: str = "investment"):
        """Cached version of get_company_facts"""
        return self._get_cached_or_execute(
            "get_company_facts",
            self.original_service.get_company_facts,
            query_type,
            ticker_symbol=ticker_symbol
        )
    
    def get_historical_financial_metrics(self, ticker_symbol: str, period: str = "ttm", 
                                       limit: int = 1, query_type: str = "investment"):
        """Cached version of get_historical_financial_metrics"""
        return self._get_cached_or_execute(
            "get_historical_financial_metrics",
            self.original_service.get_historical_financial_metrics,
            query_type,
            ticker_symbol=ticker_symbol,
            period=period,
            limit=limit
        )
    
    def get_filings(self, ticker_symbol: str, filing_type: str = "10-Q", 
                   year: Optional[int] = None, quarter: Optional[int] = None, 
                   query_type: str = "investment"):
        """Cached version of get_filings"""
        return self._get_cached_or_execute(
            "get_filings",
            self.original_service.get_filings,
            query_type,
            ticker_symbol=ticker_symbol,
            filing_type=filing_type,
            year=year,
            quarter=quarter
        )
    
    def get_insider_trades(self, ticker_symbol: str, limit: int = 10, query_type: str = "trading"):
        """Cached version of get_insider_trades"""
        return self._get_cached_or_execute(
            "get_insider_trades",
            self.original_service.get_insider_trades,
            query_type,
            ticker_symbol=ticker_symbol,
            limit=limit
        )
    
    def get_earnings_releases(self, ticker_symbol: str, query_type: str = "investment"):
        """Cached version of get_earnings_releases"""
        return self._get_cached_or_execute(
            "get_earnings_releases",
            self.original_service.get_earnings_releases,
            query_type,
            ticker_symbol=ticker_symbol
        )
    
    def get_institutional_ownership(self, ticker_symbol: str, query_type: str = "investment"):
        """Cached version of get_institutional_ownership"""
        return self._get_cached_or_execute(
            "get_institutional_ownership",
            self.original_service.get_institutional_ownership,
            query_type,
            ticker_symbol=ticker_symbol
        )
    
    def run_all_finance_tools(self, ticker_symbol: str, period: str = "ttm",
                            period_limit: int = 1, get_insider_trades_limit: int = 10,
                            filing_type: str = "10-Q", filing_year: Optional[int] = 2024,
                            filing_quarter: Optional[int] = 3, query_type: str = "comprehensive"):
        """
        Cached version of run_all_finance_tools with intelligent sub-caching
        """
        cache_params = {
            "ticker_symbol": ticker_symbol,
            "period": period,
            "period_limit": period_limit,
            "get_insider_trades_limit": get_insider_trades_limit,
            "filing_type": filing_type,
            "filing_year": filing_year,
            "filing_quarter": filing_quarter
        }
        
        # Check if complete result is cached
        cached_result, is_hit = self.cache.get(
            self.service_name, "run_all_finance_tools", cache_params, query_type
        )
        
        if is_hit:
            logger.info(f"✓ Cache HIT for run_all_finance_tools: {ticker_symbol}")
            return cached_result
        
        # If not cached, execute with individual method caching
        logger.info(f"⚡ Executing run_all_finance_tools: {ticker_symbol}")
        result = self.original_service.run_all_finance_tools(
            ticker_symbol=ticker_symbol,
            period=period,
            period_limit=period_limit,
            get_insider_trades_limit=get_insider_trades_limit,
            filing_type=filing_type,
            filing_year=filing_year,
            filing_quarter=filing_quarter
        )
        
        # Cache the complete result
        self.cache.set(self.service_name, "run_all_finance_tools", cache_params, result, query_type)
        logger.info(f"✓ Cached complete result for run_all_finance_tools")
        
        return result
    
    def invalidate_symbol_cache(self, ticker_symbol: str):
        """Invalidate all cached data for a specific symbol"""
        return self.cache.invalidate_symbol(ticker_symbol)
    
    def get_cache_stats(self):
        """Get cache performance statistics"""
        return self.cache.get_cache_stats()


class CachedNewsService:
    """Enhanced News Service with intelligent caching"""
    
    def __init__(self, original_service):
        self.original_service = original_service
        self.cache = get_cache_service()
        self.service_name = "news_service"
    
    def _get_cached_or_execute(self, method_name: str, original_method, query_type: str = "", **kwargs):
        """Generic caching wrapper for news service methods"""
        cache_params = {k: v for k, v in kwargs.items() 
                       if not k.startswith('_') and v is not None}
        
        # Try cache first
        cached_result, is_hit = self.cache.get(
            self.service_name, method_name, cache_params, query_type
        )
        
        if is_hit:
            logger.info(f"✓ Cache HIT for {method_name}: {cache_params.get('query', 'N/A')}")
            return cached_result
        
        # Execute original method
        try:
            logger.info(f"⚡ Executing {method_name}: {cache_params.get('query', 'N/A')}")
            result = original_method(**kwargs)
            
            # Cache the result
            self.cache.set(self.service_name, method_name, cache_params, result, query_type)
            logger.info(f"✓ Cached result for {method_name}")
            
            return result
            
        except Exception as e:
            logger.error(f"✗ Error in {method_name}: {str(e)}")
            raise
    
    def get_everything_news(self, query: str, from_date: Optional[str] = None, 
                          to_date: Optional[str] = None, page_size: int = 20, 
                          query_type: str = "news"):
        """Cached version of get_everything_news"""
        return self._get_cached_or_execute(
            "get_everything_news",
            self.original_service.get_everything_news,
            query_type,
            query=query,
            from_date=from_date,
            to_date=to_date,
            page_size=page_size
        )
    
    def get_top_headlines(self, query: Optional[str] = None, country: str = "us",
                         category: Optional[str] = None, page_size: int = 20,
                         query_type: str = "headlines"):
        """Cached version of get_top_headlines"""
        return self._get_cached_or_execute(
            "get_top_headlines",
            self.original_service.get_top_headlines,
            query_type,
            query=query,
            country=country,
            category=category,
            page_size=page_size
        )
    
    def get_top_articles_summary(self, query: str, from_date: Optional[str] = None,
                               to_date: Optional[str] = None, max_articles: int = 10,
                               query_type: str = "summary"):
        """Cached version of get_top_articles_summary"""
        return self._get_cached_or_execute(
            "get_top_articles_summary",
            self.original_service.get_top_articles_summary,
            query_type,
            query=query,
            from_date=from_date,
            to_date=to_date,
            max_articles=max_articles
        )


class CachedRAGService:
    """Enhanced RAG Service with intelligent caching"""
    
    def __init__(self, original_service):
        self.original_service = original_service
        self.cache = get_cache_service()
        self.service_name = "rag_service"
    
    def query(self, question: str, query_type: str = "knowledge") -> Dict[str, Any]:
        """Cached version of RAG query with semantic similarity checking"""
        
        # Normalize question for better cache matching
        normalized_question = question.lower().strip()
        cache_params = {"question": normalized_question}
        
        # Try exact cache match first
        cached_result, is_hit = self.cache.get(
            self.service_name, "rag_query", cache_params, query_type
        )
        
        if is_hit:
            logger.info(f"✓ Cache HIT for RAG query: {question[:50]}...")
            return cached_result
        
        # Check for similar questions in cache (simple keyword matching)
        similar_result = self._find_similar_cached_query(normalized_question, query_type)
        if similar_result:
            logger.info(f"✓ Similar cache HIT for RAG query: {question[:50]}...")
            return similar_result
        
        # Execute original query
        try:
            logger.info(f"⚡ Executing RAG query: {question[:50]}...")
            result = self.original_service.query(question)
            
            # Cache the result
            self.cache.set(self.service_name, "rag_query", cache_params, result, query_type)
            logger.info(f"✓ Cached RAG result")
            
            return result
            
        except Exception as e:
            logger.error(f"✗ Error in RAG query: {str(e)}")
            raise
    
    def _find_similar_cached_query(self, question: str, query_type: str) -> Optional[Dict[str, Any]]:
        """
        Find similar cached queries using simple keyword matching
        This is a simplified approach - could be enhanced with semantic similarity
        """
        try:
            # Get all cached RAG entries
            cache_entries = self.cache.memory_cache
            
            question_words = set(question.lower().split())
            
            for cache_key, entry in cache_entries.items():
                if (entry.service_type == self.service_name and 
                    "rag_query" in cache_key and 
                    self.cache._is_cache_valid(entry)):
                    
                    cached_question = entry.query_params.get("question", "")
                    cached_words = set(cached_question.lower().split())
                    
                    # Simple similarity check (could be enhanced)
                    overlap = len(question_words.intersection(cached_words))
                    similarity = overlap / max(len(question_words), len(cached_words))
                    
                    # If 70% word overlap, consider it similar enough
                    if similarity >= 0.7:
                        logger.debug(f"Found similar cached query (similarity: {similarity:.2f})")
                        return entry.data
            
        except Exception as e:
            logger.warning(f"Error checking for similar queries: {e}")
        
        return None


# Factory functions to create cached service instances
def create_cached_finance_service(original_service):
    """Create cached version of finance service"""
    return CachedFinanceService(original_service)

def create_cached_news_service(original_service):
    """Create cached version of news service"""
    return CachedNewsService(original_service)

def create_cached_rag_service(original_service):
    """Create cached version of RAG service"""
    return CachedRAGService(original_service)


# Example integration in your main application
if __name__ == "__main__":
    # Example usage - how to integrate with existing services
    from .finance_data import FinanceDataService
    from .news_data import NewsDataService
    from .rag_service import create_rag_service
    
    # Create original services
    finance_service = FinanceDataService()
    news_service = NewsDataService()
    rag_service = create_rag_service()
    
    # Wrap with caching
    cached_finance = create_cached_finance_service(finance_service)
    cached_news = create_cached_news_service(news_service)
    cached_rag = create_cached_rag_service(rag_service)
    
    # Use cached services - same interface, but with intelligent caching
    result1 = cached_finance.get_prices("AAPL", query_type="trading")
    result2 = cached_news.get_everything_news("AAPL OR Apple", query_type="trading")
    result3 = cached_rag.query("What are the best trading strategies?", query_type="strategy")
    
    # Check cache performance
    stats = cached_finance.get_cache_stats()
    print(f"Cache performance: {stats}")