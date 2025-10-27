import requests
import json
import os
from typing import Optional, Dict, Any
import concurrent.futures
import logging
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from .cache_service import get_cache_service
    CACHING_ENABLED = True
    logger.info("Cache service imported successfully")
except ImportError as e:
    logger.warning(f"Caching service not available - running without cache: {e}")
    CACHING_ENABLED = False

class FinanceDataService:
    FREE_TIER_TICKERS = os.getenv("FREE_TIER_TICKERS", "").split(",")
    
    def __init__(self, api_base_url: str = "https://api.financialdatasets.ai", api_key: Optional[str] = None):
        self.api_base_url = api_base_url.rstrip('/')
        self.api_key = api_key or os.getenv("FINANCIAL_DATASETS_API_KEY")
        self.session = requests.Session()
        
        try:
            self.cache = get_cache_service() if CACHING_ENABLED else None
            if self.cache:
                logger.info("Finance service initialized with caching enabled")
            else:
                logger.warning("Finance service initialized without caching")
        except Exception as e:
            logger.error(f"Failed to initialize cache service: {e}")
            self.cache = None
        self.service_name = "finance_service"
    
    def _get_cached_or_execute(self, method_name: str, params: Dict[str, Any], 
                              execute_func, query_type: str = ""):
        """Generic caching wrapper for finance service methods"""
        if not self.cache:
            logger.info(f"⚡ Executing {method_name} (no cache): {params.get('ticker_symbol', 'N/A')}")
            return execute_func()
        
        try:
            cached_result, is_hit = self.cache.get(
                self.service_name, method_name, params, query_type
            )
            
            if is_hit:
                logger.info(f"✓ Cache HIT for {method_name}: {params.get('ticker_symbol', 'N/A')}")
                return cached_result
        except Exception as e:
            logger.warning(f"Cache get failed for {method_name}: {e}")
        
        try:
            logger.info(f"⚡ Executing {method_name}: {params.get('ticker_symbol', 'N/A')}")
            result = execute_func()
            
            if self.cache:
                try:
                    self.cache.set(self.service_name, method_name, params, result, query_type)
                    logger.info(f"💾 Cached result for {method_name}: {params.get('ticker_symbol', 'N/A')}")
                except Exception as e:
                    logger.warning(f"Cache set failed for {method_name}: {e}")
            
            return result
        except Exception as e:
            logger.error(f"Failed to execute {method_name}: {e}")
            raise
    
    def _requires_api_key(self, ticker_symbol: str, url: str = "", body: str = "") -> bool:
        """Check if ticker requires API key based on free tier list"""
        ticker_upper = ticker_symbol.upper()
        for free_ticker in self.FREE_TIER_TICKERS:
            if (free_ticker in ticker_upper or 
                free_ticker in url.upper() or 
                free_ticker in body.upper()):
                logger.warning("Skipped API key fetch. Ticker does not require API key")
                return False
        return True
    
    def _make_request(self, endpoint: str, ticker_symbol: str, params: Optional[Dict] = None, body: str = "") -> Dict[str, Any]:
        """Execute HTTP requests with error handling"""
        url = f"{self.api_base_url}/{endpoint.lstrip('/')}"
        
        try:
            logger.info(f"Executing Request: {url}")
            
            needs_api_key = self._requires_api_key(ticker_symbol, url, body)
            
            headers = {}
            if needs_api_key and self.api_key:
                headers["X-API-KEY"] = self.api_key
                logger.info("API Key Fetched")
            elif needs_api_key and not self.api_key:
                logger.warning("No API Key named 'FINANCIAL_DATASETS_API_KEY' present. Proceeding API call without API Key.")
            
            if body:
                headers["Content-Type"] = "application/json"
                response = requests.post(url, json=json.loads(body), headers=headers, params=params)
            else:
                response = requests.get(url, headers=headers, params=params)
            
            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.warning(f"Error Response ({response.status_code}): {response.text}")
            else:
                logger.info(f"✅ Success Response: {response.text[:200]}...")
            
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            error_msg = f"Error encountered: {str(e)}"
            
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    if 'message' in error_data:
                        error_msg = f"API Error: {error_data['message']}"
                    elif 'error' in error_data:
                        error_msg = f"API Error: {error_data['error']}"
                except (json.JSONDecodeError, ValueError):
                    error_msg = f"API Error ({e.response.status_code}): {e.response.text}"
            error_msg = "❌ "+error_msg
            logger.error(error_msg)
            raise Exception(error_msg)
        
    def get_prices(self, ticker_symbol: str, start_date: Optional[str] = None, 
                   end_date: Optional[str] = None, interval: str = "minute", 
                   interval_multiplier: int = 15, query_type: str = "trading") -> Dict[str, Any]:
        """Get current or historical prices for a stock ticker"""
        logger.info(f"Get Prices - started for {ticker_symbol}")

        def execute_request():
            try:
                nonlocal start_date, end_date
                if start_date is None:
                    start_date = datetime.now().strftime("%Y-%m-%d")
                if end_date is None:
                    end_date = datetime.now().strftime("%Y-%m-%d")
                    
                params = {
                    "ticker": ticker_symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "interval": interval,
                    "interval_multiplier": interval_multiplier
                }
                result = self._make_request("prices", ticker_symbol, params)
                logger.info("Get Prices - ended")
                return result
            except Exception as e:
                logger.error(f"Get Prices failed: {str(e)}")
                raise

        cache_params = {
            "ticker_symbol": ticker_symbol,
            "start_date": start_date or datetime.now().strftime("%Y-%m-%d"),
            "end_date": end_date or datetime.now().strftime("%Y-%m-%d"),
            "interval": interval,
            "interval_multiplier": interval_multiplier
        }
        
        return self._get_cached_or_execute("get_prices", cache_params, execute_request, query_type)

    def get_company_facts(self, ticker_symbol: str, query_type: str = "investment") -> Dict[str, Any]:
        """Get company facts and basic information"""
        logger.info(f"Get Company Facts - started for {ticker_symbol}")
        
        def execute_request():
            try:
                params = {"ticker": ticker_symbol}
                result = self._make_request("company/facts", ticker_symbol, params)
                logger.info("Get Company Facts - ended")
                return result
            except Exception as e:
                logger.error(f"Get Company Facts failed: {str(e)}")
                raise
        
        cache_params = {"ticker_symbol": ticker_symbol}
        return self._get_cached_or_execute("get_company_facts", cache_params, execute_request, query_type)
    
    def get_historical_financial_metrics(self, ticker_symbol: str, period: str = "ttm", 
                                       limit: int = 1, query_type: str = "investment") -> Dict[str, Any]:
        """
        Get Historical Financial Metrics
        Based on: Get Historical Financial Metrics.xaml
        
        Args:
            ticker_symbol: Stock ticker symbol
            period: Period for metrics (default: "ttm")
            limit: Number of periods to return (default: 1)
            query_type: Context for caching (investment, research, trading)
            
        Returns:
            Historical financial metrics data
        """
        logger.info(f"Get Historical Financial Metrics - started for {ticker_symbol}")
        
        def execute_request():
            try:
                params = {
                    "ticker": ticker_symbol,
                    "period": period,
                    "limit": limit
                }
                result = self._make_request("financial-metrics", ticker_symbol, params)
                logger.info("Get Historical Financial Metrics - ended")
                return result
            except Exception as e:
                logger.error(f"Get Historical Financial Metrics failed: {str(e)}")
                raise
        
        # Use caching wrapper
        cache_params = {
            "ticker_symbol": ticker_symbol,
            "period": period,
            "limit": limit
        }
        return self._get_cached_or_execute("get_historical_financial_metrics", cache_params, execute_request, query_type)
    
    def get_filings(self, ticker_symbol: str, filing_type: str = "10-Q", 
                   year: Optional[int] = None, quarter: Optional[int] = None, 
                   query_type: str = "investment") -> Dict[str, Any]:
        """
        Get SEC Filings - Items
        Based on: Get Filings - Items.xaml
        
        Args:
            ticker_symbol: Stock ticker symbol
            filing_type: Type of filing ("10-K", "10-Q", default: "10-Q")
            year: Filing year (optional)
            quarter: Filing quarter for 10-Q (optional)
            query_type: Context for caching (investment, research, compliance)
            
        Returns:
            SEC filings data
        """
        logger.info(f"Get Filings - Items - started for {ticker_symbol}")
        
        def execute_request():
            try:
                params = {
                    "ticker": ticker_symbol,
                    "filing_type": filing_type
                }
                if year is not None:
                    params["year"] = year
                if quarter is not None:
                    params["quarter"] = quarter
                
                result = self._make_request("filings/items", ticker_symbol, params)
                logger.info("Get Filings - Items - ended")
                return result
            except Exception as e:
                logger.error(f"Get Filings - Items failed: {str(e)}")
                raise
        
        # Use caching wrapper
        cache_params = {
            "ticker_symbol": ticker_symbol,
            "filing_type": filing_type,
            "year": year,
            "quarter": quarter
        }
        return self._get_cached_or_execute("get_filings", cache_params, execute_request, query_type)
    
    def get_insider_trades(self, ticker_symbol: str, limit: int = 10, query_type: str = "trading") -> Dict[str, Any]:
        """
        Get Insider Trades
        Based on: Get Insider Trades.xaml
        
        Args:
            ticker_symbol: Stock ticker symbol
            limit: Number of trades to return (default: 10)
            query_type: Context for caching (trading, research, monitoring)
            
        Returns:
            Insider trades data
        """
        logger.info(f"Get Insider Trades - started for {ticker_symbol}")
        
        def execute_request():
            try:
                params = {
                    "ticker": ticker_symbol,
                    "limit": limit
                }
                result = self._make_request("insider-trades", ticker_symbol, params)
                logger.info("Get Insider Trades - ended")
                return result
            except Exception as e:
                logger.error(f"Get Insider Trades failed: {str(e)}")
                raise
        
        # Use caching wrapper
        cache_params = {
            "ticker_symbol": ticker_symbol,
            "limit": limit
        }
        return self._get_cached_or_execute("get_insider_trades", cache_params, execute_request, query_type)
    
    def get_earnings_releases(self, ticker_symbol: str, query_type: str = "investment") -> Dict[str, Any]:
        """
        Get Earnings Releases
        Based on: Get Earnings Releases.xaml
        
        Args:
            ticker_symbol: Stock ticker symbol
            query_type: Context for caching (investment, trading, research)
            
        Returns:
            Earnings releases data
        """
        logger.info(f"Get Earnings Releases - started for {ticker_symbol}")
        
        def execute_request():
            try:
                params = {"ticker": ticker_symbol}
                result = self._make_request("earnings/press-releases", ticker_symbol, params)
                logger.info("Get Earnings Releases - ended")
                return result
            except Exception as e:
                logger.error(f"Get Earnings Releases failed: {str(e)}")
                raise
        
        # Use caching wrapper
        cache_params = {"ticker_symbol": ticker_symbol}
        return self._get_cached_or_execute("get_earnings_releases", cache_params, execute_request, query_type)
    
    def get_institutional_ownership(self, ticker_symbol: str, query_type: str = "investment") -> Dict[str, Any]:
        """
        Get Institutional Ownership
        Based on: Get Institutional Ownership.xaml
        
        Args:
            ticker_symbol: Stock ticker symbol
            query_type: Context for caching (investment, research, analysis)
            
        Returns:
            Institutional ownership data
        """
        logger.info(f"Get Institutional Ownership - started for {ticker_symbol}")
        
        def execute_request():
            try:
                params = {"ticker": ticker_symbol}
                result = self._make_request("institutional-ownership", ticker_symbol, params)
                logger.info("Get Institutional Ownership - ended")
                return result
            except Exception as e:
                logger.error(f"Get Institutional Ownership failed: {str(e)}")
                raise
        
        # Use caching wrapper
        cache_params = {"ticker_symbol": ticker_symbol}
        return self._get_cached_or_execute("get_institutional_ownership", cache_params, execute_request, query_type)
    
    def run_all_finance_tools(
        self,
        ticker_symbol: str,
        period: str = "ttm",
        period_limit: int = 1,
        get_insider_trades_limit: int = 10,
        filing_type: str = "10-Q",
        filing_year: Optional[int] = 2024,
        filing_quarter: Optional[int] = 3,
        query_type: str = "comprehensive"
    ) -> Dict[str, Any]:
        """Execute all finance API calls in parallel and merge results"""
        logger.info("Run All Finance Tools - started")
        
        def execute_all_requests():
            def get_company_facts_task():
                return self.get_company_facts(ticker_symbol, query_type)
            
            def get_filings_task():
                return self.get_filings(ticker_symbol, filing_type, filing_year, filing_quarter, query_type)
            
            def get_insider_trades_task():
                return self.get_insider_trades(ticker_symbol, get_insider_trades_limit, query_type)
            
            def get_earnings_task():
                return self.get_earnings_releases(ticker_symbol, query_type)
            
            def get_financial_metrics_task():
                return self.get_historical_financial_metrics(ticker_symbol, period, period_limit, query_type)
            
            def get_ownership_task():
                return self.get_institutional_ownership(ticker_symbol, query_type)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                futures = {
                    'company_facts': executor.submit(get_company_facts_task),
                    'insider_trades': executor.submit(get_insider_trades_task),
                    'earnings': executor.submit(get_earnings_task),
                    'historical_financial_metrics': executor.submit(get_financial_metrics_task),
                    'institutional_ownership': executor.submit(get_ownership_task),
                    'filings': executor.submit(get_filings_task),
                }
                
                response_output = {}
                for key, future in futures.items():
                    try:
                        response_output[key] = future.result()
                    except Exception as e:
                        logger.error(f"Failed to get {key}: {str(e)}")
                        response_output[key] = {"error": str(e)}
            
            return response_output
        
        cache_params = {
            "ticker_symbol": ticker_symbol,
            "period": period,
            "period_limit": period_limit,
            "get_insider_trades_limit": get_insider_trades_limit,
            "filing_type": filing_type,
            "filing_year": filing_year,
            "filing_quarter": filing_quarter
        }
        
        result = self._get_cached_or_execute("run_all_finance_tools", cache_params, execute_all_requests, query_type)
        
        logger.info(f"Run All Finance Tools - ended. Final Response Output -> {json.dumps(result, indent=2)[:10000]}...")
        logger.info(f"Final Response Output Total Character Count: {len(json.dumps(result))}")
        
        return result
    
    def invalidate_symbol_cache(self, ticker_symbol: str) -> int:
        """Invalidate all cached data for a specific symbol"""
        if not self.cache:
            return 0
        return self.cache.invalidate_symbol(ticker_symbol)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        if not self.cache:
            return {"caching": "disabled"}
        return self.cache.get_cache_stats()
    
    def clear_cache(self) -> None:
        """Clear all cache entries"""
        if self.cache:
            self.cache.clear_all()
            logger.info("Finance service cache cleared")




# Example usage
if __name__ == "__main__":
    service = FinanceDataService()

    try:
        company_facts = service.get_company_facts("GOOGL")
        print("Company Facts:", json.dumps(company_facts, indent=2)[:500])
    except Exception as e:
        print(f"Error: {e}")
        
    try:
        prices = service.get_prices("AAPL")
        print("Prices:", json.dumps(prices, indent=2)[:500])
    except Exception as e:
        print(f"Error: {e}")
        
    try:
        all_data = service.run_all_finance_tools(
            ticker_symbol="NVDA",
            period="ttm",
            period_limit=1,
            get_insider_trades_limit=10,
            filing_type="10-Q",
            filing_year=2024,
            filing_quarter=3
        )
        print("All Finance Data keys:", list(all_data.keys()))
    except Exception as e:
        print(f"Error: {e}")