"""
Default Tools Package

Contains core tools that are commonly used across different agents:
- RAG knowledge base queries
- General-purpose utilities
"""

from .rag_tools import query_knowledge_base

__all__ = ["query_knowledge_base"]
