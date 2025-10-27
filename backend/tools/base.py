from typing import Dict, List, Callable, Any, Optional
from langchain_core.tools import BaseTool

def get_tools(tool_names: Optional[List[str]] = None, include_advanced: bool = False) -> List[BaseTool]:
    """Get specified tools or all tools if tool_names is None.
    
    Args:
        tool_names: Optional list of tool names to include. If None, returns all tools.
        include_advanced: Whether to include advanced/experimental tools. Defaults to False.
        
    Returns:
        List of tool objects
    """
    # Import default tools
    from tools.default.rag_tools import query_knowledge_base
    
    # Import quantitative analysis tools
    from tools.quant.finance_tools import get_stock_prices, run_all_finance_tools
    from tools.quant.news_tools import get_news_articles
    
    # Base tools dictionary - core tools always available
    all_tools = {
        # Knowledge base tools
        "query_knowledge_base": query_knowledge_base,
        
        # Financial data tools
        "get_stock_prices": get_stock_prices,
        "run_all_finance_tools": run_all_finance_tools,
        
        # News data tools
        "get_news_articles": get_news_articles,
    }
    
    # Add advanced tools if requested
    if include_advanced:
        try:
            # Future: Add advanced technical analysis tools
            # from tools.advanced.technical_analysis import technical_indicators
            # from tools.advanced.portfolio_tools import portfolio_optimization
            
            # all_tools.update({
            #     "technical_indicators": technical_indicators,
            #     "portfolio_optimization": portfolio_optimization,
            # })
            pass
        except ImportError:
            # If advanced tools aren't available, continue without them
            pass
    
    if tool_names is None:
        return list(all_tools.values())
    
    return [all_tools[name] for name in tool_names if name in all_tools]

def get_tools_by_name(tools: Optional[List[BaseTool]] = None) -> Dict[str, BaseTool]:
    """Get a dictionary of tools mapped by name."""
    if tools is None:
        tools = get_tools()
    
    return {tool.name: tool for tool in tools}

def get_finance_tools() -> List[BaseTool]:
    """Get only finance-related tools."""
    return get_tools([
        "get_stock_prices", 
        "run_all_finance_tools"
    ])

def get_news_tools() -> List[BaseTool]:
    """Get only news-related tools."""
    return get_tools([
        "get_news_articles"
    ])

def get_research_tools() -> List[BaseTool]:
    """Get tools for research and analysis (finance + news + knowledge base)."""
    return get_tools([
        "query_knowledge_base",
        "get_stock_prices",
        "run_all_finance_tools", 
        "get_news_articles"
    ])

def get_trading_tools() -> List[BaseTool]:
    """Get tools specifically for trading analysis."""
    return get_tools([
        "get_stock_prices",
        "get_news_articles",
        "query_knowledge_base"
    ])

def get_investment_tools() -> List[BaseTool]:
    """Get tools specifically for investment analysis."""
    return get_tools([
        "run_all_finance_tools",
        "get_news_articles", 
        "query_knowledge_base"
    ])

def list_available_tools() -> Dict[str, str]:
    """Get a list of available tools with descriptions."""
    return {
        "query_knowledge_base": "Query trading and investing knowledge base for expert information",
        "get_stock_prices": "Get current or historical stock prices for any ticker symbol",
        "run_all_finance_tools": "Run comprehensive financial analysis (company facts, metrics, filings, etc.)",
        "get_news_articles": "Get recent news articles about stocks, companies, or financial topics",
    }