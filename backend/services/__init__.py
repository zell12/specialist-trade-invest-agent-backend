"""
Services Package

Contains all the core services for the trading and investing agents:
- finance_data: FinancialDataset.ai API integration
- news_data: NewsAPI.org integration  
- rag_service: RAG knowledge base service using LangChain and ChromaDB
"""

from .finance_data import FinanceDataService
from .news_data import NewsDataService
from .rag_service import RAGService, create_rag_service

__all__ = [
    "FinanceDataService",
    "NewsDataService", 
    "RAGService",
    "create_rag_service"
]
