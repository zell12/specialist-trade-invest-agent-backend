#!/usr/bin/env python3
"""
Comprehensive cache diagnosis and test script
"""
import os
import sys
import logging
from pathlib import Path

# Add backend to path - we're in backend/test, so go up one level  
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# Configure logging to see cache operations
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_cache_service_disk_storage():
    """Test cache service with methods that should write to disk"""
    logger.info("=== Testing Cache Service with Disk Storage ===")
    
    try:
        from services.cache_service import get_cache_service, CacheLevel
        
        # Get cache service
        cache = get_cache_service()
        logger.info(f"Cache service initialized: {cache}")
        logger.info(f"Cache directory: {cache.cache_dir}")
        logger.info(f"Entries directory: {cache.entries_dir}")
        
        # Test with methods that should go to disk (MEDIUM_TERM, LONG_TERM, PERSISTENT)
        test_cases = [
            ("finance_service", "get_company_facts", {"ticker": "AAPL"}, "LONG_TERM"),
            ("finance_service", "get_historical_financial_metrics", {"ticker": "GOOGL"}, "MEDIUM_TERM"), 
            ("news_service", "get_everything_news", {"query": "AAPL earnings", "language": "en"}, "SHORT_TERM"),
            ("news_service", "get_top_headlines", {"country": "us", "category": "business"}, "IMMEDIATE"),
            ("rag_service", "rag_query", {"query": "test question"}, "PERSISTENT"),
        ]
        
        for service_name, method_name, params, expected_level in test_cases:
            logger.info(f"\n--- Testing {service_name}.{method_name} ({expected_level}) ---")
            
            # Check what cache level this method gets
            cache_level = cache._get_cache_level(service_name, method_name)
            logger.info(f"Cache level for {method_name}: {cache_level.value}")
            
            # Test cache miss
            result, is_hit = cache.get(service_name, method_name, params, "testing")
            logger.info(f"Cache miss test: hit={is_hit}")
            
            # Cache test data
            test_data = {
                "test_result": f"data_for_{method_name}",
                "timestamp": "2024-01-01",
                "value": 42.0
            }
            
            cache.set(service_name, method_name, params, test_data, "testing")
            logger.info(f"Data cached with level: {cache_level.value}")
            
            # Test cache hit
            result, is_hit = cache.get(service_name, method_name, params, "testing")
            logger.info(f"Cache hit test: hit={is_hit}, result={result}")
        
        return True
        
    except Exception as e:
        logger.error(f"Cache service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_manual_disk_cache():
    """Manually test disk cache creation"""
    logger.info("=== Testing Manual Disk Cache Creation ===")
    
    try:
        from services.cache_service import get_cache_service, CacheLevel
        
        cache = get_cache_service()
        
        # Force a PERSISTENT cache entry
        logger.info("Creating PERSISTENT cache entry...")
        
        # Manually create an entry that should go to disk
        from services.cache_service import CacheEntry
        import time
        
        cache_key = cache._generate_cache_key("test_service", "persistent_method", {"test": "param"}, "testing")
        
        entry = CacheEntry(
            data={"test": "persistent_data", "value": 123},
            timestamp=time.time(),
            cache_level=CacheLevel.PERSISTENT,
            service_type="test_service",
            cache_key=cache_key,
            content_hash=cache._get_content_hash({"test": "persistent_data"}),
            query_params=cache._normalize_params({"test": "param"}),
            data_size=50,
            access_count=1,
            last_access=time.time()
        )
        
        # Directly call _save_to_disk
        logger.info(f"Saving entry to disk with key: {cache_key}")
        cache._save_to_disk(entry)
        
        return True
        
    except Exception as e:
        logger.error(f"Manual disk cache test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cache_directory_creation():
    """Test if cache directories can be created"""
    logger.info("=== Testing Cache Directory Creation ===")
    
    try:
        from services.cache_service import get_cache_service
        
        cache = get_cache_service()
        
        # Check directories
        logger.info(f"Cache directory: {cache.cache_dir}")
        logger.info(f"Cache directory exists: {cache.cache_dir.exists()}")
        logger.info(f"Entries directory: {cache.entries_dir}")
        logger.info(f"Entries directory exists: {cache.entries_dir.exists()}")
        
        # Test file creation directly
        test_file = cache.entries_dir / "test" / "test_file.json"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(test_file, 'w') as f:
            f.write('{"test": "data"}')
        
        logger.info(f"Test file created: {test_file}")
        logger.info(f"Test file exists: {test_file.exists()}")
        
        # Clean up
        test_file.unlink()
        test_file.parent.rmdir()
        
        return True
        
    except Exception as e:
        logger.error(f"Directory creation test failed: {e}")
        import traceback
        traceback.print_exc()
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
                # Show file contents
                try:
                    with open(entry, 'r') as f:
                        content = f.read()
                        logger.info(f"    Content: {content[:100]}...")
                except Exception as e:
                    logger.warning(f"    Could not read file: {e}")
            return len(entries) > 0
        else:
            logger.warning(f"Cache directory does not exist: {cache_dir}")
            return False
            
    except Exception as e:
        logger.error(f"Error checking cache files: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting comprehensive cache diagnosis...")
    
    # Test 1: Cache directory creation
    dir_creation_ok = test_cache_directory_creation()
    
    # Test 2: Manual disk cache
    manual_cache_ok = test_manual_disk_cache()
    
    # Test 3: Cache service with disk methods
    cache_service_ok = test_cache_service_disk_storage()
    
    # Test 4: Check cache files
    cache_files_ok = check_cache_files()
    
    # Summary
    logger.info(f"\n=== Diagnostic Results ===")
    logger.info(f"Directory Creation: {'✓' if dir_creation_ok else '✗'}")
    logger.info(f"Manual Cache: {'✓' if manual_cache_ok else '✗'}")
    logger.info(f"Cache Service: {'✓' if cache_service_ok else '✗'}")
    logger.info(f"Cache Files Created: {'✓' if cache_files_ok else '✗'}")
    
    if all([dir_creation_ok, manual_cache_ok, cache_service_ok, cache_files_ok]):
        logger.info("🎉 All tests passed! Cache functionality is working.")
    else:
        logger.warning("❌ Some tests failed. Cache functionality needs debugging.")