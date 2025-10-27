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

from services.service_factory import get_finance_service


class FinancePricesInput(BaseModel):
    """Input for getting stock prices"""
    ticker_symbol: str = Field(description="Stock ticker symbol (e.g., 'AAPL', 'GOOGL', 'TSLA')")
    start_date: Optional[str] = Field(default=None, description="The start date would be based on the recommended data window which will be prior the inputted date_of_trade or prior current date if date_of_trade is not available e.g. 7 days data window for short term stock trade for date_of_trade 7/8/2025 -> start date = 7/1/2025")
    end_date: Optional[str] = Field(default=None, description="The end date would be the inputted date_of_trade. If input date_of_trade is not provided, use the current date.")
    interval: str = Field(default="minute", description="The interval must be one of {'day', 'week', 'year', 'second', 'minute', 'month'}. e.g. for 15 min candle interval --> multiplier = 15, interval = minute")
    interval_multiplier: int = Field(default=15, description="The multiplier for the interval. Required range: x > 1. e.g. for 15 min candle interval --> multiplier = 15, interval = minute")


class FinanceAllToolsInput(BaseModel):
    """Input for running all finance tools"""
    ticker_symbol: str = Field(description="Stock ticker symbol (e.g., 'AAPL', 'GOOGL', 'TSLA')")
    period: str = Field(default="ttm", description="The time period for financial data. Can be either: annual, quarterly, ttm")
    period_limit: int = Field(default=1, description="Limit for financial metrics (default: 1)")
    insider_trades_limit: int = Field(default=10, description="Limit for insider trades (default: 10)")
    filing_type: str = Field(default="10-Q", description="10-K or 10-Q")
    filing_year: Optional[int] = Field(default=2024, description="The year of the SEC filing corresponding to the inputted date_of_trade. If input date_of_trade is not provided, use current year.")
    filing_quarter: Optional[int] = Field(default=3, description="The quarter of the SEC filing corresponding to the inputted date_of_trade. If input date_of_trade is not provided, use current quarter.")


@tool("get_stock_prices", args_schema=FinancePricesInput)
def get_stock_prices(
    ticker_symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    interval: str = "minute",
    interval_multiplier: int = 15
) -> str:
    """Get current or historical stock prices for a ticker symbol"""
    try:
        logger.info(f"⚒️ Fetching stock prices for {ticker_symbol} from {start_date} to {end_date} with interval {interval_multiplier} {interval}")
        
        finance_service = get_finance_service()
        price_data = finance_service.get_prices(
            ticker_symbol=ticker_symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            interval_multiplier=interval_multiplier,
            query_type="trading"
        )
        
        if 'prices' in price_data:
            prices = price_data['prices']
            
            total_points = len(prices)
            
            if total_points == 0:
                return f"No price data found for {ticker_symbol}"
            
            result = f"+++++++++ Stock prices for {ticker_symbol} +++++++++\n\n"
            result += f"Period: {start_date or 'N/A'} to {end_date or 'N/A'}\n"
            result += f"Interval: {interval_multiplier} {interval}\n"
            result += f"Total data points: {total_points}\n\n"
            
            if total_points <= 60:
                result += "=== All Data Points ===\n"
                for i, price in enumerate(prices):
                    result += f"{i+1}. {price}\n"
            else:
                result += "=== First 25 Data Points ===\n"
                for i, price in enumerate(prices[:25]):
                    result += f"{i+1}. {price}\n"
                
                middle_start = (total_points - 10) // 2
                middle_end = middle_start + 10
                result += f"\n... [{middle_start - 25} data points omitted] ...\n\n"
                result += "=== Middle 10 Data Points ===\n"
                for i in range(middle_start, middle_end):
                    result += f"{i+1}. {prices[i]}\n"
                
                result += f"\n... [{total_points - middle_end - 25} data points omitted] ...\n\n"
                result += "=== Last 25 Data Points ===\n"
                for i, price in enumerate(prices[-25:]):
                    result += f"{total_points - 25 + i + 1}. {price}\n"
            
            try:
                closes = [p.get('c', 0) for p in prices if isinstance(p, dict) and 'c' in p]
                if closes:
                    result += "\n=== Price Statistics ===\n"
                    result += f"Current Price: ${closes[-1]:.2f}\n"
                    result += f"Period High: ${max(closes):.2f}\n"
                    result += f"Period Low: ${min(closes):.2f}\n"
                    result += f"Period Change: ${closes[-1] - closes[0]:.2f} ({((closes[-1]/closes[0] - 1) * 100):.2f}%)\n"
                    result += f"Average Price: ${sum(closes)/len(closes):.2f}\n"
            except Exception as e:
                logger.warning(f"Could not calculate price statistics: {e}")
            
            result += "\n++++++++++++++++++++++++++++++++++++++\n"
            return result
        else:
            return f"No price data found for {ticker_symbol}"
            
    except Exception as e:
        return f"Error getting stock prices for {ticker_symbol}: {str(e)}"


@tool("run_all_finance_tools", args_schema=FinanceAllToolsInput)
def run_all_finance_tools(
    ticker_symbol: str,
    period: str = "ttm",
    period_limit: int = 1,
    insider_trades_limit: int = 10,
    filing_type: str = "10-Q",
    filing_year: Optional[int] = 2024,
    filing_quarter: Optional[int] = 3
) -> str:
    """Get comprehensive financial data including metrics, filings, insider trades, and institutional ownership"""
    try:
        logger.info(f"⚒️ Running all finance tools for {ticker_symbol} with period {period}, filing_type {filing_type}, year {filing_year}, quarter {filing_quarter}")
        
        finance_service = get_finance_service()
        all_data = finance_service.run_all_finance_tools(
            ticker_symbol=ticker_symbol,
            period=period,
            period_limit=period_limit,
            get_insider_trades_limit=insider_trades_limit,
            filing_type=filing_type,
            filing_year=filing_year,
            filing_quarter=filing_quarter,
            query_type="comprehensive"
        )
        
        result = f"+++++++++ Comprehensive Financial Analysis for {ticker_symbol}: +++++++++\n\n"
        
        if 'company_facts' in all_data and not 'error' in all_data['company_facts']:
            company_data = all_data['company_facts']
            result += "=== COMPANY INFORMATION ===\n"
            result += str(company_data)
            result += "===========================\n"
        
        if 'historical_financial_metrics' in all_data and not 'error' in all_data['historical_financial_metrics']:
            metrics = all_data['historical_financial_metrics']
            result += "=== FINANCIAL METRICS ===\n"
            result += str(metrics)
            result += "===========================\n"
        
        if 'insider_trades' in all_data and not 'error' in all_data['insider_trades']:
            trades = all_data['insider_trades']
            result += "=== RECENT INSIDER TRADES ===\n"
            result += str(trades)
            result += "===========================\n"
        
        if 'earnings' in all_data and not 'error' in all_data['earnings']:
            earnings = all_data['earnings']
            result += "=== RECENT EARNINGS ===\n"
            result += str(earnings)
            result += "===========================\n"
        
        if 'institutional_ownership' in all_data and not 'error' in all_data['institutional_ownership']:
            ownership = all_data['institutional_ownership']
            result += "=== TOP INSTITUTIONAL HOLDERS ===\n"
            result += str(ownership)
            result += "===========================\n"
        
        if 'filings' in all_data and not 'error' in all_data['filings']:
            filings = all_data['filings']
            result += "=== RECENT SEC FILINGS ===\n"
            result += str(filings)
            result += "===========================\n"
        
        errors = []
        for key, value in all_data.items():
            if isinstance(value, dict) and 'error' in value:
                errors.append(f"{key}: {value['error']}")
        
        if errors:
            result += "=== ERRORS ENCOUNTERED ===\n"
            for error in errors:
                result += f"• {error}\n"
        
        return result
        
    except Exception as e:
        return f"Error running comprehensive financial analysis for {ticker_symbol}: {str(e)}"
