"""Centralized service factory with caching support"""

import logging
from typing import Optional, Dict, Any

from .finance_data import FinanceDataService
from .news_data import NewsDataService
from .rag_service import RAGService, create_rag_service as _create_rag_service

logger = logging.getLogger(__name__)

_finance_service: Optional[FinanceDataService] = None
_news_service: Optional[NewsDataService] = None
_rag_service: Optional[RAGService] = None

def get_finance_service(api_key: Optional[str] = None, use_cache: bool = True) -> FinanceDataService:
    """Get or create FinanceDataService instance with caching"""
    global _finance_service
    
    if _finance_service is None:
        _finance_service = FinanceDataService(api_key=api_key)
        if use_cache:
            logger.info("Finance service created with intelligent caching enabled")
        else:
            _finance_service.cache = None
            logger.info("Finance service created without caching")
    
    return _finance_service

def get_news_service(api_key: Optional[str] = None, use_cache: bool = True) -> NewsDataService:
    """
    Get or create NewsDataService instance with caching enabled by default.
    
    Args:
        api_key: Optional API key for News API
        use_cache: Whether to enable caching (default: True)
        
    Returns:
        NewsDataService instance with caching integrated
    """
    global _news_service
    
    if _news_service is None:
        _news_service = NewsDataService(api_key=api_key)
        if use_cache:
            logger.info("News service created with intelligent caching enabled")
        else:
            # Disable caching by setting cache to None
            _news_service.cache = None
            logger.info("News service created without caching")
    
    return _news_service

def get_rag_service(input_files_path: str = None, recreate_vector_db: bool = False, 
                   use_cache: bool = True) -> RAGService:
    """
    Get or create RAGService instance with caching enabled by default.
    
    Args:
        input_files_path: Path to input files for RAG
        recreate_vector_db: Whether to recreate the vector database
        use_cache: Whether to enable caching (default: True)
        
    Returns:
        RAGService instance with caching integrated
    """
    global _rag_service
    
    if _rag_service is None:
        if input_files_path:
            _rag_service = _create_rag_service(input_files_path, recreate_vector_db)
        else:
            # Use default path
            default_path = r"C:\Temp\_Dev\Langchain-Agents\agents-trading-investing\backend\data\sample_docs"
            _rag_service = _create_rag_service(default_path, recreate_vector_db)
        
        if use_cache:
            logger.info("RAG service created with intelligent caching enabled")
        else:
            # Disable caching by setting cache to None
            _rag_service.cache = None
            logger.info("RAG service created without caching")
    
    return _rag_service

def create_all_services(finance_api_key: Optional[str] = None,
                       news_api_key: Optional[str] = None,
                       rag_input_path: Optional[str] = None,
                       use_cache: bool = True) -> Dict[str, Any]:
    """
    Create all services with caching enabled.
    
    Args:
        finance_api_key: Optional API key for Financial Datasets API
        news_api_key: Optional API key for News API
        rag_input_path: Optional path to RAG input files
        use_cache: Whether to enable caching for all services (default: True)
        
    Returns:
        Dictionary containing all service instances
    """
    services = {
        'finance': get_finance_service(finance_api_key, use_cache),
        'news': get_news_service(news_api_key, use_cache),
        'rag': get_rag_service(rag_input_path, use_cache=use_cache)
    }
    
    logger.info(f"All services created with caching {'enabled' if use_cache else 'disabled'}")
    return services

def get_cache_stats() -> Dict[str, Any]:
    """
    Get cache performance statistics from all services.
    
    Returns:
        Combined cache statistics from all services
    """
    stats = {}
    
    # Get finance service stats
    if _finance_service and hasattr(_finance_service, 'get_cache_stats'):
        stats['finance'] = _finance_service.get_cache_stats()
    
    # Get news service stats
    if _news_service and hasattr(_news_service, 'get_cache_stats'):
        stats['news'] = _news_service.get_cache_stats()
    
    # Get RAG service stats
    if _rag_service and hasattr(_rag_service, 'get_cache_stats'):
        stats['rag'] = _rag_service.get_cache_stats()
    
    return stats

def clear_all_caches() -> None:
    """Clear all service caches."""
    cleared = []
    
    if _finance_service and hasattr(_finance_service, 'clear_cache'):
        _finance_service.clear_cache()
        cleared.append('finance')
    
    if _news_service and hasattr(_news_service, 'clear_cache'):
        _news_service.clear_cache()
        cleared.append('news')
    
    if _rag_service and hasattr(_rag_service, 'clear_cache'):
        _rag_service.clear_cache()
        cleared.append('rag')
    
    logger.info(f"Cleared caches for services: {', '.join(cleared)}")

def invalidate_symbol_caches(symbol: str) -> int:
    """
    Invalidate cached data for a specific symbol across all services.
    
    Args:
        symbol: Stock symbol to invalidate
        
    Returns:
        Total number of cache entries invalidated
    """
    total_invalidated = 0
    
    # Invalidate finance service cache
    if _finance_service and hasattr(_finance_service, 'invalidate_symbol_cache'):
        count = _finance_service.invalidate_symbol_cache(symbol)
        total_invalidated += count
        logger.info(f"Invalidated {count} finance cache entries for {symbol}")
    
    # Invalidate news service cache (news doesn't have symbol-specific invalidation yet)
    if _news_service and hasattr(_news_service, 'invalidate_cache'):
        # For news, invalidate all cache related to the symbol query
        count = _news_service.invalidate_cache(symbol)
        total_invalidated += count
        logger.info(f"Invalidated {count} news cache entries for {symbol}")
    
    # RAG service doesn't need symbol-specific invalidation as it's knowledge-based
    
    logger.info(f"Total invalidated cache entries for {symbol}: {total_invalidated}")
    return total_invalidated

def reset_all_services() -> None:
    """Reset all service instances (useful for testing or reconfiguration)."""
    global _finance_service, _news_service, _rag_service
    
    _finance_service = None
    _news_service = None
    _rag_service = None
    
    logger.info("All service instances reset")


# Backward compatibility aliases
def create_finance_service(api_key: Optional[str] = None) -> FinanceDataService:
    """Backward compatibility alias for get_finance_service."""
    return get_finance_service(api_key)

def create_news_service(api_key: Optional[str] = None) -> NewsDataService:
    """Backward compatibility alias for get_news_service."""
    return get_news_service(api_key)

def create_rag_service(input_files_path: str = None, recreate_vector_db: bool = False) -> RAGService:
    """Backward compatibility alias for get_rag_service."""
    return get_rag_service(input_files_path, recreate_vector_db)


if __name__ == "__main__":
    # Example usage and testing
    
    # Create all services with caching
    services = create_all_services()
    
    # Test finance service
    finance = services['finance']
    try:
        result = finance.get_company_facts("AAPL", query_type="testing")
        print(f"Finance service test: {len(str(result))} characters")
    except Exception as e:
        print(f"Finance service error: {e}")
    
    # Test news service
    news = services['news']
    try:
        result = news.get_top_headlines(query="Apple", query_type="testing")
        print(f"News service test: {result.get('totalResults', 0)} articles")
    except Exception as e:
        print(f"News service error: {e}")
    
    # Test RAG service
    rag = services['rag']
    try:
        result = rag.query("What is a good trading strategy?", query_type="testing")
        print(f"RAG service test: {len(result.get('answer', ''))} characters")
    except Exception as e:
        print(f"RAG service error: {e}")
    
    # Check cache stats
    stats = get_cache_stats()
    print(f"Cache stats: {stats}")