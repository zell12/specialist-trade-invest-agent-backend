import functools
import logging
import operator
import json
from typing import Dict, Any, Literal, Optional, Annotated
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from tools.base import get_research_tools, get_tools_by_name
from agents.utils.prompt_templates import SYSTEM_PROMPT_TRADE_INVEST_AGENT, USER_PROMPT_TRADE_INVEST_AGENT, FINAL_SYNTH_PROMPT_TRADE_INVEST_AGENT


class TradeInvestState(TypedDict):
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


def create_trade_invest_agent() -> StateGraph:
    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    tools = get_research_tools()
    tools_by_name = get_tools_by_name(tools)
    llm_with_tools = llm.bind_tools(tools, tool_choice="any")
    
    system_prompt = SYSTEM_PROMPT_TRADE_INVEST_AGENT

    def llm_analysis_node(state: TradeInvestState) -> TradeInvestState:
        query = state.get("query", "")
        query_type = state.get("query_type", "")
        ticker_symbol = state.get("ticker_symbol", "")
        date_of_trade = state.get("date_of_trade", "")
        trade_capital = state.get("trade_capital", 1000)
        
        context_prompt = USER_PROMPT_TRADE_INVEST_AGENT.format(
            query_type=query_type,
            query=query,
            ticker_symbol=ticker_symbol or "As specified on query, if any",
            date_of_trade=date_of_trade or datetime.now().strftime("%Y-%m-%d")
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=context_prompt)
        ] + state.get("messages", [])
        
        response = llm_with_tools.invoke(messages)
        
        return {
            **state,
            "messages": [response]
        }

    def tool_execution_node(state: TradeInvestState) -> TradeInvestState:
        last_message = state["messages"][-1]
        tool_results = []
        tool_calls_made = state.get("tool_calls_made", [])
        
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_call_id = tool_call["id"]
            
            if tool_name not in tool_calls_made:
                tool_calls_made.append(tool_name)
            
            if tool_name in tools_by_name:
                try:
                    tool = tools_by_name[tool_name]
                    result = tool.invoke(tool_args)
                    tool_results.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tool_call_id,
                            name=tool_name
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

    def synthesis_node(state: TradeInvestState) -> TradeInvestState:
        query_type = state.get("query_type", "")
        trade_capital = state.get("trade_capital", 1000)
        date_of_trade = state.get("date_of_trade", "")
        
        tool_data = []
        for msg in state.get("messages", []):
            if isinstance(msg, ToolMessage):
                tool_data.append(f"**{msg.name} Results:**\n{msg.content}\n")
        
        tool_summary = "\n".join(tool_data) if tool_data else "No tool data available."
        
        synthesis_prompt = FINAL_SYNTH_PROMPT_TRADE_INVEST_AGENT.format(
            query_type=query_type,
            tool_summary=tool_summary,
            trade_capital=trade_capital,
            date_of_trade=date_of_trade or datetime.now().strftime("%Y-%m-%d")
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=synthesis_prompt)
        ]
        
        final_response = llm.invoke(messages)
        
        try:
            content = final_response.content.replace('```json','').replace('```','')
            logger.info(f">>> Final response content cleaned: {content}")
            trade_recommendation = json.loads(content)                
        except json.JSONDecodeError as e:
            trade_recommendation = {
                "error": f"Invalid JSON response: {str(e)}",
                "raw_response": final_response.content,
                "query_type": query_type
            }
        
        return {
            **state,
            "messages": [final_response],
            "trade_recommendation": trade_recommendation
        }

    def should_continue(state: TradeInvestState) -> Literal["tools", "synthesis"]:
        last_message = state["messages"][-1]
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"
        return "synthesis"
    
    def should_continue_after_tools(state: TradeInvestState) -> Literal["analysis", "synthesis"]:
        tool_calls_made = state.get("tool_calls_made", [])
        
        if len(tool_calls_made) >= 3:
            return "synthesis"
        
        return "analysis"
    
    graph = StateGraph(TradeInvestState)
    
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
    agent = create_trade_invest_agent()
    
    test_state = {
        "query": "AAPL long term investment",
        "date_of_trade": "8/22/2025",
        "trade_capital": 5000.0,
        "query_type": "investing"
    }
    
    print("Testing Trade/Invest Agent (LangGraph Implementation)...")
    print("=" * 60)
    
    try:
        result = agent.invoke(test_state)
        print("✅ Agent executed successfully!")
        print(f"📊 Tools used: {result.get('tool_calls_made', [])}")
        print(f"💰 Trade recommendation: {result.get('trade_recommendation') if result.get('trade_recommendation') else 'No'}")
        
        if result.get("messages"):
            latest_message = result["messages"][-1]
            print(f"📝 Response preview: {latest_message.content[:200]}...")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        
    print("=" * 60)
