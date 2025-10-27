import logging
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool
import sys
from pathlib import Path

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import service factory instead of direct service
from services.service_factory import get_rag_service


class RAGQueryInput(BaseModel):
    """Input for RAG knowledge base query"""
    question: str = Field(description="Question to ask the knowledge base (e.g., 'What are the best trading strategies?', 'How to analyze financial statements?')")


# Global RAG service instance (initialized once)
_rag_service = None


def _get_rag_service():
    """Get or create the RAG service instance"""
    global _rag_service
    if _rag_service is None:
        # Use default path or OneDrive books path
        input_files_path = r"C:\Users\RusselAlfeche\OneDrive\Books - Trading and Investing"
        # Use service factory to get cached RAG service
        _rag_service = get_rag_service(
            input_files_path=input_files_path,
            recreate_vector_db=False  # Always use existing vector store
        )
    return _rag_service


@tool("query_knowledge_base", args_schema=RAGQueryInput)
def query_knowledge_base(question: str) -> str:
    """
    This is the Complete Guide to Trading and Investing Literature.
    Query the trading and investing knowledge base for information about trading strategies, 
    financial analysis, market insights, and investment guidance.
    
    This tool searches through a comprehensive collection of trading and investing books 
    and documents to provide detailed, expert-level answers to financial questions.
    
    Use this tool when you need:
    - Trading strategies and techniques
    - Financial analysis methods
    - Investment principles and guidance
    - Market analysis approaches
    - Risk management strategies
    - Technical analysis information
    - Fundamental analysis techniques
    
    Args:
        question: Question to ask the knowledge base (e.g., "What are the best momentum trading strategies?", 
                 "How do I analyze a company's financial statements?", "What is risk management in trading?")
    
    Returns:
        Detailed answer from the knowledge base with source document references
    """
    try:
        logger.info(f"⚒️ Querying knowledge base for question: {question}")
        
        rag_service = _get_rag_service()
        # Pass query context for better caching
        result = rag_service.query(question, query_type="knowledge")
        
        # Format the response
        answer = result.get('answer', 'No answer found')
        source_documents = result.get('source_documents', [])
        
        response = f"Knowledge Base Answer:\n\n{answer}\n\n"
        
        if source_documents:
            response += f"Sources ({len(source_documents)} documents):\n"
            for i, doc in enumerate(source_documents, 1):
                file_name = doc.get('file_name', 'Unknown')
                content_preview = doc.get('content_preview', 'No preview available')
                response += f"{i}. {file_name}\n"
                response += f"   Excerpt: {content_preview}\n\n"
        else:
            response += "No source documents found.\n"
        
        return response
        
    except Exception as e:
        return f"Error querying knowledge base: {str(e)}"