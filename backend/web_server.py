"""
FastAPI Web Server for Trading AI Agent
Serves the frontend and provides API endpoints for trading recommendations
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

try:
    from agents.main_graph import create_trading_system, TradingInput
    print("✅ Successfully imported trading system")
except ImportError as e:
    print(f"❌ Error importing trading system: {e}")
    create_trading_system = None
    TradingInput = None

try:
    from services.uipath.job_service import UiPathJobService
    print("✅ Successfully imported UiPath service")
    uipath_service = UiPathJobService()
except ImportError as e:
    print(f"❌ Error importing UiPath service: {e}")
    uipath_service = None

from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Trading AI Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

trading_system = None
if create_trading_system:
    try:
        trading_system = create_trading_system()
        print("✅ Trading system initialized successfully")
    except Exception as e:
        print(f"❌ Error initializing trading system: {e}")
class TradingQueryRequest(BaseModel):
    query: str
    date_of_trade: str
    trade_capital: float

class ExitAnalysisRequest(BaseModel):
    trade_recommendation: Dict[str, Any]
    date_of_trade: str

frontend_dir = Path(__file__).parent / "web"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

@app.get("/")
async def serve_frontend():
    """Serve the main frontend HTML file"""
    frontend_file = frontend_dir / "index.html"
    if frontend_file.exists():
        return FileResponse(str(frontend_file))
    else:
        raise HTTPException(status_code=404, detail="Frontend not found")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "trading_system_available": trading_system is not None,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/trading-query")
async def get_trading_recommendation(request: TradingQueryRequest):
    """Get trading recommendation from the AI agent"""
    
    if not trading_system:
        raise HTTPException(
            status_code=503, 
            detail="Trading system not available. Please check backend configuration."
        )
    
    try:
        if TradingInput:
            trading_input = TradingInput(
                query=request.query,
                date_of_trade=request.date_of_trade,
                trade_capital=request.trade_capital
            )
        else:
            trading_input = {
                "query": request.query,
                "date_of_trade": request.date_of_trade,
                "trade_capital": request.trade_capital
            }
        
        print(f"🔄 Processing trading query: {request.query}")
        print(f"📅 Trade date: {request.date_of_trade}")
        print(f"💰 Capital: ${request.trade_capital}")
        
        if os.getenv("USE_UIPATH_JOB_SERVICE", "false").lower() == "false":
            print("🤖 Using trading system agent graph")
            result = await asyncio.get_event_loop().run_in_executor(
                None, trading_system.invoke, trading_input
            )
        else:
            print("🤖 Using UiPath job service for trading agent run")
            job_result = await asyncio.get_event_loop().run_in_executor(
                None, uipath_service.start_job_and_wait, "trading-investing-agent", trading_input
            )
            result = job_result.get('output_arguments', {})

        print(f"✅ Trading recommendation generated successfully")
        print(f"📊 Query type: {result.get('query_type', 'unknown')}")
        
        query_type = result.get("query_type", "trading")
        
        if query_type == "trading":
            recommendation = result.get("trade_recommendation", {})
            return {
                "query_type": "trading",
                "trading_response": recommendation.get("trading_response", {})
            }
        elif query_type == "investing" or query_type == "investment":
            recommendation = result.get("trade_recommendation", {})
            return {
                "query_type": "investment", 
                "investment_response": recommendation.get("investment_response", {})
            }
        else:
            return {
                "query_type": "other",
                "response": result.get("response", "Query processed successfully")
            }
            
    except Exception as e:
        print(f"❌ Error processing trading query: {str(e)}")
        import traceback
        traceback.print_exc()
        
        raise HTTPException(
            status_code=500,
            detail=f"Error processing trading query: {str(e)}"
        )

@app.post("/api/exit-analysis")
async def get_exit_analysis(request: ExitAnalysisRequest):
    """Get exit analysis for a trading recommendation"""
    
    if not trading_system:
        raise HTTPException(
            status_code=503,
            detail="Trading system not available. Please check backend configuration."
        )
    
    try:
        print(f"🔄 Processing exit analysis request")
        print(f"📅 Trade date: {request.date_of_trade}")
        
        exit_input = {
            "query": "exit_analysis",
            "query_type": "exit_analysis",
            "date_of_trade": request.date_of_trade,
            "trade_capital": 0,
            "ticker_symbol": "",
            "trade_recommendation": request.trade_recommendation,
            "exit_analysis": None,
            "next": "",
            "tool_calls_made": []
        }
        
        result = await asyncio.get_event_loop().run_in_executor(
            None, trading_system.invoke, exit_input
        )
        
        print(f"✅ Exit analysis completed successfully")
        
        exit_analysis = result.get("exit_analysis", {})
        
        if not exit_analysis:
            raise HTTPException(
                status_code=500,
                detail="No exit analysis data returned"
            )
        
        return exit_analysis
            
    except Exception as e:
        print(f"❌ Error processing exit analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        
        raise HTTPException(
            status_code=500,
            detail=f"Error processing exit analysis: {str(e)}"
        )
        

@app.get("/api/status")
async def get_system_status():
    """Get system status and configuration"""
    return {
        "trading_system_available": trading_system is not None,
        "uipath_service_available": uipath_service is not None,
        "backend_version": "1.0.0",
        "python_version": sys.version,
        "environment": os.getenv("ENVIRONMENT", "development"),
        "timestamp": datetime.now().isoformat()
    }

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return {"error": "Endpoint not found", "path": str(request.url.path)}

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    return {"error": "Internal server error", "detail": str(exc)}

if __name__ == "__main__":
    print("🚀 Starting Trading AI Agent Web Server...")
    print(f"📁 Frontend directory: {frontend_dir}")
    print(f"🔧 Trading system available: {trading_system is not None}")
    
    uvicorn.run(
        "web_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
