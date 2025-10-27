import functools
import logging
import operator
from typing import Dict, Any, Literal, Optional, Annotated
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from datetime import datetime, timedelta
import sys
from pathlib import Path
import json

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from tools.base import get_tools, get_tools_by_name
from agents.utils.prompt_templates import (
    SYSTEM_PROMPT_TRADE_EXIT_AGENT,
    USER_PROMPT_TRADE_EXIT_AGENT, 
    FINAL_SYNTH_PROMPT_TRADE_EXIT_AGENT
)


class TradeExitState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    query: str
    query_type: str
    date_of_trade: Optional[str]
    trade_capital: float
    ticker_symbol: Optional[str]
    trade_recommendation: Optional[dict]
    exit_analysis: Optional[dict]
    next: str
    tool_calls_made: list[str]
    trade_params: Optional[dict]



def create_trade_exit_agent() -> StateGraph:
    llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
    tools = get_tools(["get_stock_prices", "query_knowledge_base"])
    tools_by_name = get_tools_by_name(tools)
    llm_with_tools = llm.bind_tools(tools, tool_choice="any")
    
    def extract_trade_parameters(trade_recommendation: dict, date_of_trade: str) -> dict:
        """Extract trade parameters from trade_recommendation JSON structure"""
        
        if isinstance(trade_recommendation, dict) and "trading_response" in trade_recommendation:
            trading_data = trade_recommendation["trading_response"]
            
            symbol = trading_data.get("symbol", "")
            entry_price = float(trading_data.get("entry_price", 0))
            stop_loss = float(trading_data.get("stop_loss", 0))
            target_price = float(trading_data.get("target_price", 0))
            quantity = int(trading_data.get("quantity", 1))
            
            action = trading_data.get("action_recommendation", "BUY")
            side = "BUY" if action in ["BUY", "LONG CALL", "LONG PUT"] else "SELL"
            
            entry_time_date = trading_data.get("entry_time_date", date_of_trade)
            try:
                if "/" in entry_time_date:
                    parts = entry_time_date.split("/")
                    if len(parts) == 3:
                        month, day, year = parts
                        entry_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    else:
                        entry_date = date_of_trade
                elif "T" in entry_time_date or " " in entry_time_date:
                    dt = datetime.fromisoformat(entry_time_date.replace("T", " "))
                    entry_time = dt.strftime("%H:%M:%S")
                    entry_date = dt.strftime("%Y-%m-%d")
                elif "-" in entry_time_date:
                    entry_date = entry_time_date
                    entry_time = "09:30:00"
                else:
                    entry_date = date_of_trade
                    entry_time = "09:30:00"
                    
                if 'entry_time' not in locals():
                    entry_time = "09:30:00"
                    
            except Exception as e:
                print(f"[DEBUG] Date parsing error: {e}, using fallback")
                entry_date = date_of_trade
                entry_time = "09:30:00"
        
        return {
            "symbol": symbol,
            "entry_date": entry_date,
            "entry_time": entry_time,
            "entry_price": entry_price,
            "quantity": quantity,
            "side": side,
            "stop_loss": stop_loss,
            "target_price": target_price
        }

    def llm_analysis_node(state: TradeExitState) -> TradeExitState:
        trade_recommendation = state.get("trade_recommendation", {})
        date_of_trade = state.get("date_of_trade")
        
        logger.info(f"Trade recommendation input: {trade_recommendation}")
        logger.info(f"Date of trade: {date_of_trade}")

        if not trade_recommendation or not date_of_trade:
            return {
                **state,
                "messages": [HumanMessage(content="No trade recommendation or date provided for exit analysis.")],
                "exit_analysis": None
            }
        
        trade_params = extract_trade_parameters(trade_recommendation, date_of_trade)
        logger.info(f"Extracted trade parameters: {trade_params}")
        
        if not trade_params["symbol"] or trade_params["entry_price"] <= 0:
            error_msg = f"Invalid trade parameters: symbol='{trade_params['symbol']}', entry_price={trade_params['entry_price']}"
            logger.warning(f"{error_msg}")
            return {
                **state,
                "messages": [HumanMessage(content=error_msg)],
                "exit_analysis": None
            }
        
        user_prompt = USER_PROMPT_TRADE_EXIT_AGENT.format(
            symbol=trade_params["symbol"],
            entry_date=trade_params["entry_date"],
            entry_time=trade_params["entry_time"],
            entry_price=trade_params["entry_price"],
            quantity=trade_params["quantity"],
            side=trade_params["side"],
            stop_loss=trade_params["stop_loss"],
            target_price=trade_params["target_price"]
        )
        
        messages = [
            SystemMessage(content=SYSTEM_PROMPT_TRADE_EXIT_AGENT),
            HumanMessage(content=user_prompt)
        ] + state.get("messages", [])
        
        updated_state = {
            **state,
            "messages": [llm_with_tools.invoke(messages)],
            "trade_params": trade_params
        }
        
        return updated_state

    def tool_execution_node(state: TradeExitState) -> TradeExitState:
        last_message = state["messages"][-1]
        tool_results = []
        tool_calls_made = state.get("tool_calls_made", [])
        trade_params = state.get("trade_params", {})
        
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_call_id = tool_call["id"]
            
            if tool_name not in tool_calls_made:
                tool_calls_made.append(tool_name)
            
            if tool_name == "get_stock_prices" and trade_params.get("symbol"):
                symbol = trade_params.get("symbol")
                entry_date = trade_params.get("entry_date")
                
                try:
                    trade_date = datetime.strptime(entry_date, "%Y-%m-%d")
                    end_date = trade_date + timedelta(days=30)
                    end_date_str = end_date.strftime("%Y-%m-%d")
                    
                    tool_args.update({
                        "ticker_symbol": symbol,
                        "start_date": entry_date,
                        "end_date": end_date_str,
                        "interval": "minute",
                        "interval_multiplier": 30
                    })
                except:
                    tool_args.update({
                        "ticker_symbol": symbol,
                        "interval": "day",
                        "interval_multiplier": 1
                    })
            
            if tool_name in tools_by_name:
                try:
                    tool = tools_by_name[tool_name]
                    result = tool.invoke(tool_args)
                    tool_results.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tool_call_id,
                            name=tool_name + f"[args: {str(tool_args)}]"
                        )
                    )
                except Exception as e:
                    tool_results.append(
                        ToolMessage(
                            content=f"Error executing {tool_name}: {str(e)}",
                            tool_call_id=tool_call_id,
                            name=tool_name
                        )
                    )
        
        return {
            **state,
            "messages": tool_results,
            "tool_calls_made": tool_calls_made
        }

    def synthesis_node(state: TradeExitState) -> TradeExitState:
        """Synthesize final exit analysis using structured JSON output"""
        trade_params = state.get("trade_params", {})
        
        if not trade_params:
            return {
                **state,
                "exit_analysis": {"error": "No trade parameters available for synthesis"}
            }
        
        tool_data = []
        for msg in state.get("messages", []):
            if isinstance(msg, ToolMessage):
                tool_data.append(f"**{msg.name} Results:**\n{msg.content}\n")
        
        tool_summary = "\n".join(tool_data) if tool_data else "No tool data available."
        
        synthesis_prompt = FINAL_SYNTH_PROMPT_TRADE_EXIT_AGENT.format(
            symbol=trade_params.get("symbol", ""),
            entry_date=trade_params.get("entry_date", ""),
            entry_time=trade_params.get("entry_time", ""),
            entry_price=trade_params.get("entry_price", 0),
            quantity=trade_params.get("quantity", 1),
            side=trade_params.get("side", "BUY"),
            stop_loss=trade_params.get("stop_loss", 0),
            target_price=trade_params.get("target_price", 0),
            tool_summary=tool_summary
        )
        
        messages = [
            SystemMessage(content="You are an AI agent designed to simulate trade exits based on given stock trade inputs and historical price data."),
            HumanMessage(content=synthesis_prompt)
        ]
        
        response = llm.invoke(messages)
        
        exit_analysis = None
        try:
            content = response.content
            
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                json_content = content[json_start:json_end].strip()
            elif "{" in content and "}" in content:
                json_start = content.find("{")
                json_end = content.rfind("}") + 1
                json_content = content[json_start:json_end]
            else:
                json_content = content
            
            exit_analysis = json.loads(json_content)
              
            exit_reason = exit_analysis["exit_reason"]
            exit_price = float(exit_analysis["exit_trade"]["price"])
            target_price = float(trade_params.get("target_price", 0))
            stop_loss = float(trade_params.get("stop_loss", 0))
            if (exit_reason == "Target Hit" and exit_price < target_price) or (exit_reason == "Stop Loss Hit" and exit_price > stop_loss):
                exit_analysis["exit_reason"] = "Timed Exit"
            
            logger.info(f">>> Final response content cleaned: {str(exit_analysis)}")
            
        except Exception as e:
            exit_analysis = {
                "error": f"Invalid JSON response: {str(e)}",
                "raw_response": response.content
            }
        
        return {
            **state,
            "exit_analysis": exit_analysis,
            "messages": [response]
        }

    def should_continue(state: TradeExitState) -> Literal["tools", "synthesis"]:
        last_message = state["messages"][-1]
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"
        return "synthesis"
    
    def should_continue_after_tools(state: TradeExitState) -> Literal["analysis", "synthesis"]:
        tool_calls_made = state.get("tool_calls_made", [])
        
        if "get_stock_prices" in tool_calls_made:
            return "synthesis"
        
        return "analysis"
    
    graph = StateGraph(TradeExitState)
    
    graph.add_node("analysis", llm_analysis_node)
    graph.add_node("tools", tool_execution_node)
    graph.add_node("synthesis", synthesis_node)
    
    graph.add_edge(START, "analysis")
    
    graph.add_conditional_edges(
        "analysis",
        should_continue,
        {
            "tools": "tools",
            "synthesis": "synthesis"
        }
    )
    
    graph.add_conditional_edges(
        "tools",
        should_continue_after_tools,
        {
            "analysis": "analysis",
            "synthesis": "synthesis"
        }
    )
    
    graph.add_edge("synthesis", END)
    
    return graph.compile()


if __name__ == "__main__":
    agent = create_trade_exit_agent()
    
    test_state = {
        "messages": [],
        "query": "AAPL short term trade analysis",
        "query_type": "trading", 
        "date_of_trade": "2025-08-22",  
        "trade_capital": 4950.0,  
        "ticker_symbol": "AAPL",
        "trade_recommendation": {
            'query_type': 'trading', 
            'trading_response': {
                'analysis': 'Based on the recent price data and market trends, AAPL is showing a strong upward momentum with a recent breakout above resistance levels. This aligns with swing trading strategies that capitalize on short-term price movements.', 
                'instrument_type': 'STOCKS', 
                'symbol': 'AAPL', 
                'action_recommendation': 'BUY', 
                'entry_price': 225.0, 
                'stop_loss': 220.0, 
                'target_price': 230.0, 
                'entry_time_date': '8/22/2025', 
                'quantity': 22, 
                'options_strike_price': None, 
                'options_expiry': None
            }
        },
        "exit_analysis": None,
        "next": "",
        "tool_calls_made": []
    }
    
    print("Testing Trade Exit Agent (LangGraph Implementation)...")
    print("=" * 60)
    
    try:
        result = agent.invoke(test_state)
        if result.get("exit_analysis"):
            print("✅ Agent executed successfully!")
            print(f"📈 Exit analysis: {result.get('exit_analysis')}")

        if result.get("messages"):
            latest_message = result["messages"][-1]
            print(f"📝 Last Response preview: {latest_message.content[:200]}...")
            print(f"📊 Tools used: {result.get('tool_calls_made', [])}")
            tool_data = []
            for msg in result.get("messages", []):
                if isinstance(msg, ToolMessage):
                    tool_data.append(f"**{msg.name}**\n\n Results --> {msg.content}\n")
            print(f"⚒️ Get Stock Prices Output: {str(tool_data)}")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        
    print("=" * 60)
