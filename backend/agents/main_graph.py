import functools
import operator
import os
from datetime import datetime
from typing import Annotated, List, Optional
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

if os.getenv("LANGSMITH_TRACING", "false").lower() == "true":
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_API_KEY", "")
    os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "trading-investing-agent")

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from tools.base import get_research_tools, get_trading_tools, get_tools
from agents.trade_invest_agent import create_trade_invest_agent
from agents.trade_exit_agent import create_trade_exit_agent


class TradingInput(TypedDict):
    query: str
    date_of_trade: Optional[str]
    trade_capital: Optional[float]


class TradingSystemState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    query: str
    query_type: str
    date_of_trade: Optional[str]
    trade_capital: float
    ticker_symbol: Optional[str]
    trade_recommendation: Optional[dict]
    exit_analysis: Optional[dict]
    next: str


def initialize_state(state: TradingInput) -> TradingSystemState:
    return {
        "messages": [HumanMessage(content=state["query"])],
        "query": state["query"],
        "query_type": "",
        "date_of_trade": state.get("date_of_trade"),
        "trade_capital": state.get("trade_capital", 1000.0),
        "ticker_symbol": None,
        "trade_recommendation": None,
        "exit_analysis": None,
        "next": ""
    }


def classify_query(state: TradingSystemState) -> TradingSystemState:
    llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
    
    classification_prompt = """
    You are a query classifier for a trading and investing system. 
    
    Your tasks:
    1. Classify the query into one of these categories:
       - "trading" - Any questions about trading equities or options (day trading, swing trading, technical analysis, leaps, etc)
       - "investing" - Long-term investment questions (fundamental analysis, company research, portfolio building, long-term strategies)
       - "other" - Questions not related to trading or investing
    
    2. Extract the ticker symbol if any company/stock is mentioned. Consider:
       - Direct ticker symbols (AAPL, GOOGL, TSLA, etc.)
       - Company names (Apple -> AAPL, Microsoft -> MSFT, Tesla -> TSLA, Google -> GOOGL, Amazon -> AMZN, etc.)
       - Common variations (Meta -> META, Berkshire -> BRK.B, etc.)
    
    Query: {query}
    
    Respond in this exact format:
    Category: [trading/investing/other]
    Ticker: [TICKER_SYMBOL or NONE if no stock mentioned]
    
    Examples:
    Query: "AAPL short term trade analysis"
    Category: trading
    Ticker: AAPL
    
    Query: "Should I invest in Apple for the long term?"
    Category: investing  
    Ticker: AAPL
    
    Query: "Tesla swing trading strategy"
    Category: trading
    Ticker: TSLA
    
    Query: "What's the weather today?"
    Category: other
    Ticker: NONE
    """
    
    response = llm.invoke([
        SystemMessage(content=classification_prompt.format(query=state["query"]))
    ])
    
    response_text = response.content.strip()
    lines = response_text.split('\n')
    
    query_type = "other"
    ticker_symbol = None
    
    for line in lines:
        line = line.strip()
        if line.startswith('Category:'):
            category = line.replace('Category:', '').strip().lower()
            if category in ["trading", "investing", "other"]:
                query_type = category
        elif line.startswith('Ticker:'):
            ticker = line.replace('Ticker:', '').strip().upper()
            if ticker != "NONE":
                ticker_symbol = ticker
    
    return {
        **state,
        "query_type": query_type,
        "ticker_symbol": ticker_symbol,
        "next": query_type
    }


def handle_other_queries(state: TradingSystemState) -> TradingSystemState:
    response_message = """
    I'm sorry, but I can only help with trading and investing related questions. 
    
    Here are some example questions I can help you with:
    
    **Trading Questions:**
    • "AAPL short term trade for the week"
    • "Technical analysis for TSLA swing trading"
    • "Day trading setup for NVDA"
    • "What are the best entry and exit points for GOOGL this week?"
    
    **Investing Questions:**
    • "Long-term investment analysis for Microsoft"
    • "Should I add Amazon to my portfolio?"
    • "Fundamental analysis of Apple stock"
    • "What are the best dividend stocks for retirement?"
    
    **Input Format:**
    {
        "query": "Your trading or investing question",
        "date_of_trade": "2024-01-15",  // Optional: YYYY-MM-DD format
        "trade_capital": 5000.0         // Optional: defaults to $1000
    }
    
    Please ask me a trading or investing related question!
    """
    
    return {
        **state,
        "messages": [HumanMessage(content=response_message)],
        "next": "FINISH"
    }


def route_query(state: TradingSystemState) -> str:
    if state["query_type"] == "other":
        return "other_handler"
    elif state["query_type"] == "exit_analysis":
        return "trade_exit_agent"
    elif state["query_type"] in ["trading", "investing"]:
        return "trade_invest_agent"
    else:
        return "other_handler"


def check_historical_trade(state: TradingSystemState) -> str:
    if (state["query_type"] == "trading" and 
        state.get("date_of_trade") and 
        state.get("trade_recommendation")):
        return "trade_exit_agent"
    else:
        return "FINISH"


llm = ChatOpenAI(model="gpt-4o", temperature=0.2)


def create_trading_system():
    trade_invest_agent = create_trade_invest_agent()
    trade_exit_agent = create_trade_exit_agent()
    
    graph = StateGraph(TradingSystemState, input=TradingInput)
    
    graph.add_node("initialize", initialize_state)
    graph.add_node("classifier", classify_query)
    graph.add_node("other_handler", handle_other_queries)
    graph.add_node("trade_invest_agent", trade_invest_agent)
    graph.add_node("trade_exit_agent", trade_exit_agent)
    
    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "classifier")
    
    graph.add_conditional_edges(
        "classifier",
        route_query,
        {
            "other_handler": "other_handler",
            "trade_invest_agent": "trade_invest_agent",
            "trade_exit_agent": "trade_exit_agent"
        }
    )
    
    graph.add_edge("other_handler", END)
    
    graph.add_conditional_edges(
        "trade_invest_agent",
        check_historical_trade,
        {
            "trade_exit_agent": "trade_exit_agent",
            "FINISH": END
        }
    )
    
    graph.add_edge("trade_exit_agent", END)
    
    return graph.compile()


trading_chain = create_trading_system()


if __name__ == "__main__":
    test_inputs = [
        {
            "query": "AAPL short term trade for the week",
            "trade_capital": 1000.0
        },
        {
            "query": "TSLA swing trading analysis",
            "date_of_trade": "2024-01-15",
            "trade_capital": 5000.0
        },
        {
            "query": "Long-term investment analysis for Microsoft"
        },
        {
            "query": "What is the weather today?"
        },
        {
            "query": "NVDA day trading setup",
            "trade_capital": 2000.0
        }
    ]
    
    print("=== Trading and Investing Agent System ===\n")
    
    for i, test_input in enumerate(test_inputs, 1):
        print(f"Test Input {i}: {test_input}")
        print("=" * 50)
        
        try:
            for output in trading_chain.stream(test_input):
                for key, value in output.items():
                    if key != "__start__":
                        print(f"Node: {key}")
                        if "messages" in value and value["messages"]:
                            latest_message = value["messages"][-1]
                            print(f"Response: {latest_message.content}...")
                        print("---")
        except Exception as e:
            print(f"Error: {str(e)}")
        
        print(f"{'='*50}\n")
