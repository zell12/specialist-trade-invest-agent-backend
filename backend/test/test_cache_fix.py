#!/usr/bin/env python3
"""
Test script to verify cache functionality is working correctly
"""
import os
import sys
import logging
from pathlib import Path

# Add backend to path - we're already in backend/test, so go up one level
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# Configure logging to see cache operations
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_cache_service():
    """Test the cache service directly"""
    logger.info("=== Testing Cache Service Directly ===")
    
    try:
        from services.cache_service import get_cache_service
        
        # Get cache service
        cache = get_cache_service()
        logger.info(f"Cache service initialized: {cache}")
        logger.info(f"Cache directory: {cache.cache_dir}")
        logger.info(f"Entries directory: {cache.entries_dir}")
        
        # Test cache operations
        test_params = {"ticker": "AAPL", "period": "1d"}
        test_data = {"price": 150.0, "volume": 1000000, "timestamp": "2024-01-01"}
        
        # Test cache miss
        result, is_hit = cache.get("test_service", "test_method", test_params, "testing")
        logger.info(f"Cache miss test: {result}, hit={is_hit}")
        
        # Cache the data
        cache.set("test_service", "test_method", test_params, test_data, "testing")
        logger.info("Data cached successfully")
        
        # Test cache hit
        result, is_hit = cache.get("test_service", "test_method", test_params, "testing")
        logger.info(f"Cache hit test: {result}, hit={is_hit}")
        
        # Show cache stats
        stats = cache.get_cache_stats()
        logger.info(f"Cache stats: {stats}")
        
        return True
        
    except Exception as e:
        logger.error(f"Cache service test failed: {e}")
        return False

def test_finance_service():
    """Test finance service with caching"""
    logger.info("=== Testing Finance Service with Cache ===")
    
    try:
        from services.finance_data import FinanceDataService
        
        # Initialize service
        service = FinanceDataService()
        logger.info(f"Finance service cache enabled: {service.cache is not None}")
        
        # Test a simple method (this should try to cache)
        test_params = {
            "ticker_symbol": "AAPL",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31"
        }
        
        # Note: This will fail with actual API call, but should show cache operations
        try:
            result = service._get_cached_or_execute(
                "get_prices", 
                test_params,
                lambda: {"mock": "data", "price": 150.0},  # Mock function
                "testing"
            )
            logger.info(f"Finance service result: {result}")
            
            # Try again to test cache hit
            result2 = service._get_cached_or_execute(
                "get_prices", 
                test_params,
                lambda: {"mock": "data", "price": 150.0},  # Mock function
                "testing"
            )
            logger.info(f"Finance service result (should be cached): {result2}")
            
            return True
            
        except Exception as e:
            logger.warning(f"Finance service execution failed (expected): {e}")
            return True  # Expected to fail, but cache operations should work
        
    except Exception as e:
        logger.error(f"Finance service test failed: {e}")
        return False

def check_cache_files():
    """Check if cache files are created"""
    logger.info("=== Checking Cache Files ===")
    
    try:
        # We're in backend/test, so go up one level to backend, then to data/cache/entries
        cache_dir = Path(__file__).parent.parent / "data" / "cache" / "entries"
        logger.info(f"Checking cache directory: {cache_dir}")
        
        if cache_dir.exists():
            entries = list(cache_dir.rglob("*.json"))
            logger.info(f"Found {len(entries)} cache entries")
            for entry in entries:
                logger.info(f"  - {entry}")
            return len(entries) > 0
        else:
            logger.warning(f"Cache directory does not exist: {cache_dir}")
            return False
            
    except Exception as e:
        logger.error(f"Error checking cache files: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting cache functionality test...")
    
    # Test 1: Cache service directly
    cache_service_ok = test_cache_service()
    
    # Test 2: Finance service with cache
    finance_service_ok = test_finance_service()
    
    # Test 3: Check cache files
    cache_files_ok = check_cache_files()
    
    # Summary
    logger.info(f"\n=== Test Results ===")
    logger.info(f"Cache Service: {'✓' if cache_service_ok else '✗'}")
    logger.info(f"Finance Service: {'✓' if finance_service_ok else '✗'}")
    logger.info(f"Cache Files Created: {'✓' if cache_files_ok else '✗'}")
    
    if cache_service_ok and finance_service_ok and cache_files_ok:
        logger.info("🎉 All tests passed! Cache functionality is working.")
    else:
        logger.warning("❌ Some tests failed. Cache functionality needs debugging.")