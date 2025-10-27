#!/usr/bin/env python3
"""
Simple cache test to verify cache files are created on disk
"""
import os
import sys
import logging
from pathlib import Path

# Add backend to path - we're in backend/test, so go up one level
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Test cache file creation"""
    logger.info("Testing cache file creation...")
    
    try:
        from services.cache_service import get_cache_service
        
        # Initialize cache
        cache = get_cache_service()
        logger.info(f"✓ Cache service initialized")
        logger.info(f"  Cache directory: {cache.cache_dir}")
        logger.info(f"  Entries directory: {cache.entries_dir}")
        
        # Clear any existing cache files for clean test
        import shutil
        if cache.entries_dir.exists():
            shutil.rmtree(cache.entries_dir)
            cache.entries_dir.mkdir(parents=True, exist_ok=True)
        
        # Test with methods that should go to disk
        test_cases = [
            ("test_service", "test_method", {"param": "value1"}),  # Should be PERSISTENT now
            ("finance_service", "get_company_facts", {"ticker": "AAPL"}),  # LONG_TERM
            ("rag_service", "rag_query", {"query": "test"})  # PERSISTENT
        ]
        
        for service_name, method_name, params in test_cases:
            logger.info(f"\n--- Testing {service_name}.{method_name} ---")
            
            # Check cache level
            cache_level = cache._get_cache_level(service_name, method_name)
            logger.info(f"Cache level: {cache_level.value}")
            
            # Set cache data
            test_data = {
                "result": f"test_data_for_{method_name}",
                "timestamp": "2024-01-01",
                "service": service_name
            }
            
            cache.set(service_name, method_name, params, test_data, "testing")
            logger.info(f"✓ Cache data set for {method_name}")
            
            # Verify cache retrieval
            result, hit = cache.get(service_name, method_name, params, "testing")
            logger.info(f"✓ Cache retrieval: hit={hit}, data={result}")
        
        # Check cache files
        logger.info(f"\n--- Checking cache files ---")
        entries = list(cache.entries_dir.rglob("*.json"))
        logger.info(f"Cache files created: {len(entries)}")
        
        for entry in entries:
            logger.info(f"  - {entry.name}")
            try:
                with open(entry, 'r') as f:
                    import json
                    content = json.load(f)
                    logger.info(f"    Service: {content.get('service_type', 'N/A')}")
                    logger.info(f"    Cache level: {content.get('cache_level', 'N/A')}")
            except Exception as e:
                logger.warning(f"    Could not read file: {e}")
        
        success = len(entries) > 0
        logger.info(f"\n{'SUCCESS' if success else 'FAILED'}: {'Cache files created' if success else 'No cache files created'}")
        return success
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    main()