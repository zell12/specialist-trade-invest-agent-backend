# Multi-Level Intelligent Caching Service
import json
import hashlib
import time
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path
import logging
from dataclasses import dataclass, asdict
from enum import Enum
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)

class CacheLevel(Enum):
    """Cache levels for different data types and freshness requirements"""
    IMMEDIATE = "immediate"      # 1-5 minutes - Price data, breaking news
    SHORT_TERM = "short_term"    # 15-60 minutes - Company news, basic metrics
    MEDIUM_TERM = "medium_term"  # 2-8 hours - Financial statements, earnings
    LONG_TERM = "long_term"      # 1-7 days - Company facts, SEC filings
    PERSISTENT = "persistent"    # Weeks/months - RAG knowledge base

@dataclass
class CacheEntry:
    """Structured cache entry with metadata"""
    data: Any
    timestamp: float
    cache_level: CacheLevel
    service_type: str
    cache_key: str
    content_hash: str
    query_params: Dict[str, Any]
    data_size: int
    access_count: int = 0
    last_access: float = 0

class IntelligentCacheService:
    """
    Multi-level caching service optimized for financial data with smart invalidation
    """
    
    # Cache TTL settings (in seconds)
    CACHE_TTL = {
        CacheLevel.IMMEDIATE: 300,      # 5 minutes
        CacheLevel.SHORT_TERM: 3600,    # 1 hour  
        CacheLevel.MEDIUM_TERM: 14400,  # 4 hours
        CacheLevel.LONG_TERM: 86400,    # 24 hours
        CacheLevel.PERSISTENT: 604800   # 7 days
    }
    
    # Service-specific cache level mappings
    SERVICE_CACHE_LEVELS = {
        # Finance service mappings
        "get_prices": CacheLevel.IMMEDIATE,
        "get_company_facts": CacheLevel.LONG_TERM,
        "get_historical_financial_metrics": CacheLevel.MEDIUM_TERM,
        "get_filings": CacheLevel.LONG_TERM,
        "get_insider_trades": CacheLevel.SHORT_TERM,
        "get_earnings_releases": CacheLevel.MEDIUM_TERM,
        "get_institutional_ownership": CacheLevel.MEDIUM_TERM,
        "run_all_finance_tools": CacheLevel.SHORT_TERM,
        
        # News service mappings
        "get_everything_news": CacheLevel.SHORT_TERM,
        "get_top_headlines": CacheLevel.IMMEDIATE,
        "get_top_articles_summary": CacheLevel.SHORT_TERM,
        
        # RAG service mappings
        "rag_query": CacheLevel.PERSISTENT,
        "rag_vector_search": CacheLevel.PERSISTENT,
        
        # Test methods - force to disk for testing
        "test_method": CacheLevel.PERSISTENT,
        "persistent_method": CacheLevel.PERSISTENT,
        "test_disk_cache": CacheLevel.LONG_TERM
    }
    
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            # Get absolute path to backend/data/cache relative to this file
            current_file = Path(__file__)
            project_root = current_file.parent.parent  # Go up from services to backend
            cache_dir = project_root / "data" / "cache"
        
        self.cache_dir = Path(cache_dir)
        self.entries_dir = self.cache_dir / "entries"
        
        # Create cache directories
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Cache service initialized with directory: {self.cache_dir}")
        
        # In-memory cache for fastest access
        self.memory_cache: Dict[str, CacheEntry] = {}
        
        # Cache statistics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "invalidations": 0,
            "memory_entries": 0,
            "disk_entries": 0
        }
        
        # Thread lock for concurrent access
        self._lock = threading.Lock()
        
        # Load existing cache from disk
        self._load_cache_index()
        
        logger.info(f"Cache service initialized. Directory: {self.cache_dir}")
    
    def _generate_cache_key(self, service_name: str, method_name: str, 
                           params: Dict[str, Any], query_type: str = "") -> str:
        """
        Generate intelligent cache key based on service, method, and normalized parameters
        """
        # Normalize parameters for consistent caching
        normalized_params = self._normalize_params(params)
        
        # Add query type for context-aware caching
        key_components = {
            "service": service_name,
            "method": method_name,
            "params": normalized_params,
            "query_type": query_type
        }
        
        # Create deterministic hash
        key_string = json.dumps(key_components, sort_keys=True)
        cache_key = hashlib.sha256(key_string.encode()).hexdigest()[:16]
        
        return f"{service_name}_{method_name}_{cache_key}"
    
    def _normalize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize parameters for consistent caching across similar queries
        """
        normalized = {}
        
        for key, value in params.items():
            # Normalize ticker symbols
            if key in ["ticker", "ticker_symbol", "symbol"] and isinstance(value, str):
                normalized[key] = value.upper().strip()
            
            # Normalize date formats
            elif key in ["start_date", "end_date", "from_date", "to_date"] and value:
                try:
                    # Convert to standard YYYY-MM-DD format
                    if isinstance(value, str):
                        # Handle various date formats
                        from datetime import datetime
                        dt = datetime.strptime(value, "%Y-%m-%d")
                        normalized[key] = dt.strftime("%Y-%m-%d")
                    else:
                        normalized[key] = str(value)
                except:
                    normalized[key] = str(value)
            
            # Normalize query strings (case-insensitive, trimmed)
            elif key in ["query", "q"] and isinstance(value, str):
                normalized[key] = value.lower().strip()
            
            # Keep other params as-is
            else:
                normalized[key] = value
        
        return normalized
    
    def _get_content_hash(self, data: Any) -> str:
        """Generate hash of data content for duplicate detection"""
        content_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.md5(content_str.encode()).hexdigest()[:12]
    
    def _should_cache_response(self, data: Any, service_name: str, method_name: str) -> bool:
        """
        Determine if response should be cached based on content and context
        """
        # Don't cache error responses
        if isinstance(data, dict):
            if "error" in data or "Error" in str(data):
                return False
            
            # Don't cache empty or minimal responses
            if not data or len(str(data)) < 50:
                return False
        
        # Don't cache if no useful data
        if data is None or (isinstance(data, (list, dict)) and len(data) == 0):
            return False
        
        return True
    
    def _get_cache_level(self, service_name: str, method_name: str) -> CacheLevel:
        """Get appropriate cache level for service method"""
        method_key = method_name.replace(f"{service_name}_", "")
        return self.SERVICE_CACHE_LEVELS.get(method_key, CacheLevel.SHORT_TERM)
    
    def _is_cache_valid(self, entry: CacheEntry) -> bool:
        """Check if cache entry is still valid"""
        if not entry:
            return False
        
        current_time = time.time()
        ttl = self.CACHE_TTL.get(entry.cache_level, 3600)
        
        return (current_time - entry.timestamp) < ttl
    
    def _get_cache_file_path(self, cache_key: str) -> Path:
        """Get file path for disk cache"""
        # Create subdirectories based on cache key for better organization
        subdir = cache_key[:2]
        cache_subdir = self.entries_dir / subdir
        cache_subdir.mkdir(parents=True, exist_ok=True)
        return cache_subdir / f"{cache_key}.json"
    
    def _save_to_disk(self, entry: CacheEntry) -> None:
        """Save cache entry to disk for persistence"""
        try:
            cache_file = self._get_cache_file_path(entry.cache_key)
            logger.debug(f"Attempting to save cache entry to: {cache_file}")
            
            # Convert entry to dict for JSON serialization
            entry_dict = asdict(entry)
            entry_dict['cache_level'] = entry.cache_level.value
            
            with open(cache_file, 'w') as f:
                json.dump(entry_dict, f, indent=2, default=str)
            
            logger.info(f"Successfully saved cache entry to disk: {entry.cache_key} -> {cache_file}")
            
        except Exception as e:
            logger.error(f"Failed to save cache entry {entry.cache_key} to disk: {e}")
            raise
    
    def _load_from_disk(self, cache_key: str) -> Optional[CacheEntry]:
        """Load cache entry from disk"""
        try:
            cache_file = self._get_cache_file_path(cache_key)
            
            if not cache_file.exists():
                return None
            
            with open(cache_file, 'r') as f:
                entry_dict = json.load(f)
            
            # Convert back to CacheEntry
            entry_dict['cache_level'] = CacheLevel(entry_dict['cache_level'])
            entry = CacheEntry(**entry_dict)
            
            # Check if still valid
            if self._is_cache_valid(entry):
                logger.debug(f"Loaded valid cache entry from disk: {cache_key}")
                return entry
            else:
                # Remove expired entry
                cache_file.unlink(missing_ok=True)
                logger.debug(f"Removed expired cache entry: {cache_key}")
                return None
            
        except Exception as e:
            logger.warning(f"Failed to load cache entry {cache_key} from disk: {e}")
            return None
    
    def _load_cache_index(self) -> None:
        """Load cache index and cleanup expired entries"""
        try:
            entries_dir = self.cache_dir / "entries"
            if not entries_dir.exists():
                return
            
            valid_count = 0
            expired_count = 0
            
            # Scan all cache files
            for cache_file in entries_dir.rglob("*.json"):
                cache_key = cache_file.stem
                entry = self._load_from_disk(cache_key)
                
                if entry:
                    # Keep in memory for immediate access (for high-frequency items)
                    cache_level = entry.cache_level
                    if cache_level in [CacheLevel.IMMEDIATE, CacheLevel.SHORT_TERM]:
                        self.memory_cache[cache_key] = entry
                    valid_count += 1
                else:
                    expired_count += 1
            
            logger.info(f"Cache index loaded: {valid_count} valid, {expired_count} expired entries")
            
        except Exception as e:
            logger.warning(f"Failed to load cache index: {e}")
    
    def get(self, service_name: str, method_name: str, params: Dict[str, Any], 
            query_type: str = "") -> Tuple[Optional[Any], bool]:
        """
        Get cached data if available and valid
        
        Returns:
            Tuple of (data, is_cache_hit)
        """
        cache_key = self._generate_cache_key(service_name, method_name, params, query_type)
        
        with self._lock:
            # Check memory cache first
            if cache_key in self.memory_cache:
                entry = self.memory_cache[cache_key]
                if self._is_cache_valid(entry):
                    # Update access statistics
                    entry.access_count += 1
                    entry.last_access = time.time()
                    
                    self.stats["hits"] += 1
                    logger.info(f"Cache HIT (memory): {service_name}.{method_name} -> {cache_key}")
                    return entry.data, True
                else:
                    # Remove expired entry from memory
                    del self.memory_cache[cache_key]
            
            # Check disk cache
            entry = self._load_from_disk(cache_key)
            if entry:
                # Move to memory cache if frequently accessed
                cache_level = entry.cache_level
                if cache_level in [CacheLevel.IMMEDIATE, CacheLevel.SHORT_TERM]:
                    self.memory_cache[cache_key] = entry
                
                # Update access statistics
                entry.access_count += 1
                entry.last_access = time.time()
                
                self.stats["hits"] += 1
                logger.info(f"Cache HIT (disk): {service_name}.{method_name} -> {cache_key}")
                return entry.data, True
            
            # Cache miss
            self.stats["misses"] += 1
            logger.info(f"Cache MISS: {service_name}.{method_name} -> {cache_key}")
            return None, False
    
    def set(self, service_name: str, method_name: str, params: Dict[str, Any], 
            data: Any, query_type: str = "") -> None:
        """
        Cache response data with intelligent storage strategy
        """
        # Check if response should be cached
        if not self._should_cache_response(data, service_name, method_name):
            logger.debug(f"Skipping cache for {service_name}.{method_name} - invalid response")
            return
        
        cache_key = self._generate_cache_key(service_name, method_name, params, query_type)
        cache_level = self._get_cache_level(service_name, method_name)
        
        # Create cache entry
        entry = CacheEntry(
            data=data,
            timestamp=time.time(),
            cache_level=cache_level,
            service_type=service_name,
            cache_key=cache_key,
            content_hash=self._get_content_hash(data),
            query_params=self._normalize_params(params),
            data_size=len(str(data)),
            access_count=1,
            last_access=time.time()
        )
        
        with self._lock:
            # Store in memory for immediate/short-term data
            if cache_level in [CacheLevel.IMMEDIATE, CacheLevel.SHORT_TERM]:
                self.memory_cache[cache_key] = entry
                logger.info(f"Cached in memory: {service_name}.{method_name} -> {cache_key}")
            
            # Store on disk for medium/long-term data
            if cache_level in [CacheLevel.MEDIUM_TERM, CacheLevel.LONG_TERM, CacheLevel.PERSISTENT]:
                self._save_to_disk(entry)
                logger.info(f"Cached on disk: {service_name}.{method_name} -> {cache_key}")
        
        logger.info(f"Successfully cached response: {service_name}.{method_name} ({cache_level.value}) with key: {cache_key}")
    
    def invalidate_symbol(self, symbol: str) -> int:
        """
        Invalidate all cache entries for a specific symbol
        """
        symbol_upper = symbol.upper()
        invalidated_count = 0
        
        with self._lock:
            # Invalidate memory cache
            keys_to_remove = []
            for cache_key, entry in self.memory_cache.items():
                if any(symbol_upper in str(param_value).upper() 
                      for param_value in entry.query_params.values()):
                    keys_to_remove.append(cache_key)
            
            for key in keys_to_remove:
                del self.memory_cache[key]
                invalidated_count += 1
            
            # Invalidate disk cache
            entries_dir = self.cache_dir / "entries"
            if entries_dir.exists():
                for cache_file in entries_dir.rglob("*.json"):
                    try:
                        entry = self._load_from_disk(cache_file.stem)
                        if entry and any(symbol_upper in str(param_value).upper() 
                                       for param_value in entry.query_params.values()):
                            cache_file.unlink(missing_ok=True)
                            invalidated_count += 1
                    except Exception as e:
                        logger.warning(f"Error checking cache file {cache_file}: {e}")
        
        self.stats["invalidations"] += invalidated_count
        logger.info(f"Invalidated {invalidated_count} cache entries for symbol: {symbol}")
        return invalidated_count
    
    def invalidate_service(self, service_name: str, method_name: str = None) -> int:
        """
        Invalidate cache entries for specific service/method
        """
        invalidated_count = 0
        
        with self._lock:
            # Invalidate memory cache
            keys_to_remove = []
            for cache_key, entry in self.memory_cache.items():
                if entry.service_type == service_name:
                    if method_name is None or method_name in cache_key:
                        keys_to_remove.append(cache_key)
            
            for key in keys_to_remove:
                del self.memory_cache[key]
                invalidated_count += 1
            
            # Invalidate disk cache
            entries_dir = self.cache_dir / "entries"
            if entries_dir.exists():
                for cache_file in entries_dir.rglob("*.json"):
                    if service_name in cache_file.name:
                        if method_name is None or method_name in cache_file.name:
                            cache_file.unlink(missing_ok=True)
                            invalidated_count += 1
        
        self.stats["invalidations"] += invalidated_count
        logger.info(f"Invalidated {invalidated_count} cache entries for {service_name}.{method_name or 'all'}")
        return invalidated_count
    
    def cleanup_expired(self) -> int:
        """
        Cleanup expired cache entries
        """
        cleaned_count = 0
        
        with self._lock:
            # Cleanup memory cache
            keys_to_remove = []
            for cache_key, entry in self.memory_cache.items():
                if not self._is_cache_valid(entry):
                    keys_to_remove.append(cache_key)
            
            for key in keys_to_remove:
                del self.memory_cache[key]
                cleaned_count += 1
            
            # Cleanup disk cache
            entries_dir = self.cache_dir / "entries"
            if entries_dir.exists():
                for cache_file in entries_dir.rglob("*.json"):
                    try:
                        entry = self._load_from_disk(cache_file.stem)
                        if not entry:  # Will be None if expired and already deleted
                            cleaned_count += 1
                    except Exception as e:
                        logger.warning(f"Error checking cache file {cache_file}: {e}")
        
        logger.info(f"Cleaned up {cleaned_count} expired cache entries")
        return cleaned_count
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache performance statistics
        """
        with self._lock:
            self.stats["memory_entries"] = len(self.memory_cache)
            
            # Count disk entries
            disk_count = 0
            entries_dir = self.cache_dir / "entries"
            if entries_dir.exists():
                disk_count = len(list(entries_dir.rglob("*.json")))
            self.stats["disk_entries"] = disk_count
            
            # Calculate hit rate
            total_requests = self.stats["hits"] + self.stats["misses"]
            hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
            
            return {
                **self.stats,
                "hit_rate_percent": round(hit_rate, 2),
                "total_requests": total_requests
            }
    
    def clear_all(self) -> None:
        """
        Clear all cache entries (memory and disk)
        """
        with self._lock:
            # Clear memory cache
            self.memory_cache.clear()
            
            # Clear disk cache
            entries_dir = self.cache_dir / "entries"
            if entries_dir.exists():
                import shutil
                shutil.rmtree(entries_dir)
                entries_dir.mkdir(parents=True, exist_ok=True)
            
            # Reset stats
            self.stats = {
                "hits": 0,
                "misses": 0,
                "invalidations": 0,
                "memory_entries": 0,
                "disk_entries": 0
            }
        
        logger.info("Cleared all cache entries")


# Global cache instance
_cache_service: Optional[IntelligentCacheService] = None

def get_cache_service() -> IntelligentCacheService:
    """Get or create global cache service instance"""
    global _cache_service
    if _cache_service is None:
        _cache_service = IntelligentCacheService()
    return _cache_service

def cache_response(service_name: str, method_name: str, query_type: str = ""):
    """
    Decorator to automatically cache service method responses
    
    Usage:
        @cache_response("finance_service", "get_prices", "trading")
        def get_prices(self, ticker, start_date=None, end_date=None):
            # Method implementation
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            cache = get_cache_service()
            
            # Extract parameters for cache key (excluding 'self')
            func_params = {}
            if args and hasattr(args[0], '__class__'):
                # Skip 'self' parameter
                param_names = func.__code__.co_varnames[1:func.__code__.co_argcount]
                func_params.update(dict(zip(param_names, args[1:])))
            else:
                param_names = func.__code__.co_varnames[:func.__code__.co_argcount]
                func_params.update(dict(zip(param_names, args)))
            
            func_params.update(kwargs)
            
            # Try to get from cache
            cached_data, is_hit = cache.get(service_name, method_name, func_params, query_type)
            if is_hit:
                logger.debug(f"Returning cached result for {service_name}.{method_name}")
                return cached_data
            
            # Execute function and cache result
            try:
                result = func(*args, **kwargs)
                cache.set(service_name, method_name, func_params, result, query_type)
                return result
            except Exception as e:
                logger.error(f"Error in {service_name}.{method_name}: {e}")
                raise
        
        return wrapper
    return decorator


if __name__ == "__main__":
    # Test cache service
    cache = IntelligentCacheService("./test_cache")
    
    # Test data
    test_params = {"ticker": "AAPL", "start_date": "2024-01-01"}
    test_data = {"price": 150.0, "volume": 1000000}
    
    # Test cache miss
    result, is_hit = cache.get("finance_service", "get_prices", test_params, "trading")
    print(f"Cache miss: {result}, {is_hit}")
    
    # Cache the data
    cache.set("finance_service", "get_prices", test_params, test_data, "trading")
    
    # Test cache hit
    result, is_hit = cache.get("finance_service", "get_prices", test_params, "trading")
    print(f"Cache hit: {result}, {is_hit}")
    
    # Test stats
    stats = cache.get_cache_stats()
    print(f"Cache stats: {stats}")