import os
import logging
import warnings
import hashlib
import json
from typing import List, Optional, Dict, Any
from pathlib import Path
from tqdm import tqdm

# LangChain imports
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    TextLoader,
    PyPDFLoader,
    Docx2txtLoader,
    CSVLoader
)
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.schema import Document
from langchain_chroma import Chroma

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress PyPDF loggers
logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("pypdf.generic._data_structures").setLevel(logging.ERROR)
logging.getLogger("pypdf._page_labels").setLevel(logging.ERROR)

# Import caching system
try:
    from .cache_service import get_cache_service
    CACHING_ENABLED = True
    logger.info("Cache service imported successfully")
except ImportError as e:
    logger.warning(f"Caching service not available - running without cache: {e}")
    CACHING_ENABLED = False


class SimplePDFLoader:
    """Simple PDF loader that skips problematic PDFs"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
    
    def load(self) -> List[Document]:
        """Load PDF and skip if problematic"""
        try:
            # Suppress warnings for this operation
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                loader = PyPDFLoader(self.file_path)
                documents = loader.load()
                
                if documents:
                    logger.info(f"✓ Loaded {len(documents)} pages from {Path(self.file_path).name}")
                
                return documents
                
        except Exception as e:
            error_msg = str(e).lower()
            
            # Skip known problematic PDFs
            if any(pattern in error_msg for pattern in [
                "invalid elementary object",
                "pdfreadeerror", 
                "corrupt",
                "invalid pdf",
                "malformed"
            ]):
                logger.warning(f"⚠ Skipping problematic PDF {Path(self.file_path).name}")
                return []
            else:
                logger.error(f"✗ Error loading {Path(self.file_path).name}: {str(e)}")
                raise


class RAGService:
    def __init__(
        self,
        input_files_path: str,
        persist_directory: str = "./backend/data/chroma_db",
        chunk_size: int = 1000,
        chunk_overlap: int = 100
    ):
        self.input_files_path = Path(input_files_path)
        self.persist_directory = persist_directory
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # Initialize LLM
        self.llm_api_key = os.getenv("OPENAI_API_KEY")
        if not self.llm_api_key:
            raise ValueError("LLM API key is required")
        
        # Initialize Components
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len
        )
        self.vector_store = None
        self.qa_chain = None
        
        # Initialize caching
        try:
            self.cache = get_cache_service() if CACHING_ENABLED else None
            if self.cache:
                logger.info("RAG service initialized with caching enabled")
            else:
                logger.warning("RAG service initialized without caching")
        except Exception as e:
            logger.error(f"Failed to initialize cache service: {e}")
            self.cache = None
        self.service_name = "rag_service"
        
        # Path for persistent duplicate tracking
        self.processed_files_db = Path(self.persist_directory) / "processed_files.json"
    
    def _get_file_list(self) -> List[Path]:
        """Get list of files to process"""
        supported_extensions = {'.txt', '.pdf', '.docx', '.csv'}
        files = []
        
        for file_path in self.input_files_path.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                files.append(file_path)
        
        return files
    
    def _get_file_hash(self, file_path: Path) -> str:
        """Generate MD5 hash of file content for duplicate detection"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                # Read file in chunks to handle large files efficiently
                for chunk in iter(lambda: f.read(8192), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            logger.warning(f"Could not hash file {file_path.name}: {str(e)}")
            # Fallback to path-based identifier if hashing fails
            return f"path_{str(file_path.resolve())}"
    
    def _load_processed_files(self) -> Dict[str, Dict[str, Any]]:
        """Load previously processed files from persistent storage"""
        if self.processed_files_db.exists():
            try:
                with open(self.processed_files_db, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} previously processed files from database")
                    return data
            except Exception as e:
                logger.warning(f"Could not load processed files database: {str(e)}")
        return {}
    
    def _save_processed_files(self, processed_files: Dict[str, Dict[str, Any]]) -> None:
        """Save processed files to persistent storage"""
        try:
            os.makedirs(self.processed_files_db.parent, exist_ok=True)
            with open(self.processed_files_db, 'w', encoding='utf-8') as f:
                json.dump(processed_files, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {len(processed_files)} processed files to database")
        except Exception as e:
            logger.warning(f"Could not save processed files database: {str(e)}")
    
    def _is_file_already_processed(self, file_path: Path, file_hash: str, processed_files: Dict[str, Dict[str, Any]]) -> tuple[bool, str]:
        """Check if file was already processed in previous sessions"""
        if file_hash in processed_files:
            file_info = processed_files[file_hash]
            original_name = file_info.get('file_name', 'unknown')
            
            # Additional check: verify file still exists and hasn't changed
            try:
                original_path = file_info.get('file_path')
                if original_path and Path(original_path).exists():
                    # File exists at original location
                    return True, original_name
                else:
                    # Original file might have been moved/renamed, but content hash matches
                    return True, f"{original_name} (moved/renamed)"
            except Exception:
                return True, original_name
        
        return False, ""
    
    def create_vector_store(self, recreate_vector_db: bool = False) -> None:
        """Create vector store by streaming documents directly"""
        
        # Check if NOT for vector db recreation
        if not recreate_vector_db:
            try:
                logger.info("Loading existing vector store...")
                self.vector_store = Chroma(
                    persist_directory=self.persist_directory,
                    embedding_function=self.embeddings
                )
                logger.info("Vector store loaded successfully with existing embeddings.")
                return
            except Exception as e:
                logger.warning(f"Failed to load existing vector store: {e}. Creating new one...")
        
        logger.info("Creating new vector store by streaming documents...")
        
        # Check if input path exists
        if not self.input_files_path.exists():
            logger.error(f"Input files path does not exist: {self.input_files_path}")
            return
        
        # Get file list
        files = self._get_file_list()
        if not files:
            logger.warning("No supported files found")
            return
        
        logger.info(f"Found {len(files)} files to process")
        
        # Simple loaders
        loaders = {
            '.txt': TextLoader,
            '.pdf': SimplePDFLoader,
            '.docx': Docx2txtLoader,
            '.csv': CSVLoader
        }
        
        # Initialize vector store flag
        vector_store_created = False
        total_chunks = 0
        
        # Track processed files to avoid duplicates (using content hash)
        # Load previously processed files from persistent storage
        processed_files_db = self._load_processed_files()
        processed_file_hashes = set(processed_files_db.keys())
        processed_file_names = {k: v.get('file_name', 'unknown') for k, v in processed_files_db.items()}
        
        # Statistics
        success_count = 0
        error_count = 0
        skipped_count = 0
        duplicate_count = 0
        
        try:
            os.makedirs(self.persist_directory, exist_ok=True)
            
            # Process files one by one and immediately add to vector store
            with tqdm(files, desc="Processing documents", unit="file") as pbar:
                for file_path in pbar:
                    file_extension = file_path.suffix.lower()
                    
                    # Update progress bar
                    pbar.set_postfix({
                        'file': file_path.name[:15] + '...' if len(file_path.name) > 15 else file_path.name,
                        'success': success_count,
                        'errors': error_count,
                        'skipped': skipped_count,
                        'duplicates': duplicate_count,
                        'chunks': total_chunks
                    })
                    
                    # Create file identifier for duplicate detection using content hash
                    file_hash = self._get_file_hash(file_path)
                    
                    # Check for duplicates based on content (including previous sessions)
                    is_duplicate, original_name = self._is_file_already_processed(file_path, file_hash, processed_files_db)
                    if is_duplicate:
                        duplicate_count += 1
                        logger.info(f"⚠ Skipping duplicate file: {file_path.name} (same content as {original_name})")
                        continue
                    
                    # Mark file as being processed (add to current session tracking)
                    processed_file_hashes.add(file_hash)
                    processed_file_names[file_hash] = file_path.name
                    processed_files_db[file_hash] = {
                        'file_name': file_path.name,
                        'file_path': str(file_path),
                        'file_size': file_path.stat().st_size,
                        'file_type': file_extension
                    }
                    
                    if file_extension in loaders:
                        try:
                            # Load this single file
                            loader_class = loaders[file_extension]
                            loader = loader_class(str(file_path))
                            file_docs = loader.load()
                            
                            if file_docs:
                                # Add metadata to documents
                                for doc in file_docs:
                                    doc.metadata.update({
                                        'source': str(file_path),
                                        'file_name': file_path.name,
                                        'file_type': file_extension,
                                        'file_size': file_path.stat().st_size
                                    })
                                
                                # Split documents into chunks
                                chunks = []
                                for doc in file_docs:
                                    try:
                                        doc_chunks = self.text_splitter.split_documents([doc])
                                        chunks.extend(doc_chunks)
                                    except Exception as e:
                                        logger.warning(f"Error splitting document {file_path.name}: {str(e)}")
                                
                                if chunks:
                                    # Create vector store with first batch of chunks or add to existing
                                    if not vector_store_created:
                                        logger.info(f"Creating initial vector store with {len(chunks)} chunks from {file_path.name}")
                                        self.vector_store = Chroma.from_documents(
                                            documents=chunks,
                                            persist_directory=self.persist_directory,
                                            embedding=self.embeddings
                                        )
                                        vector_store_created = True
                                    else:
                                        # Add chunks to existing vector store
                                        logger.info(f"Adding {len(chunks)} chunks from {file_path.name} to existing vector store")
                                        self.vector_store.add_documents(chunks)
                                    
                                    total_chunks += len(chunks)
                                    logger.info(f"✓ Added {len(chunks)} chunks from {file_path.name} (total: {total_chunks})")
                                    
                                    # Save updated processed files database
                                    self._save_processed_files(processed_files_db)
                                    
                                success_count += 1
                            else:
                                skipped_count += 1
                                logger.warning(f"⚠ No content extracted from {file_path.name}")
                            
                        except Exception as e:
                            error_count += 1
                            logger.error(f"✗ Failed to process {file_path.name}: {str(e)}")
                    else:
                        skipped_count += 1
            
            # Final statistics
            logger.info(f"Document processing complete:")
            logger.info(f"  ✓ Successfully processed: {success_count} files")
            logger.info(f"  ✗ Errors: {error_count} files")
            logger.info(f"  ⚠ Skipped: {skipped_count} files")
            logger.info(f"  📋 Duplicates skipped: {duplicate_count} files")
            logger.info(f"  📄 Total chunks in vector store: {total_chunks}")
            
            if not vector_store_created:
                logger.warning("No vector store created - no valid documents found.")
            else:
                logger.info("Vector store created successfully with streaming approach.")
            
        except Exception as e:
            logger.error(f"Error creating vector store: {str(e)}")
            raise

    def initialize_qa_chain(self, retriever_k: int=4) -> None:
        """Initialize the question-answering chain"""
        if not self.vector_store:
            logger.error("Vector store not initialized. Call create_vector_store() first.")
            return

        self.qa_chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=self.vector_store.as_retriever(search_kwargs={"k": retriever_k}),
            return_source_documents=True,
            verbose=False
        )
        logger.info("Question-answering chain initialized successfully.")
    
    def _find_similar_cached_query(self, question: str, query_type: str) -> Optional[Dict[str, Any]]:
        """
        Find similar cached queries using simple keyword matching
        This is a simplified approach - could be enhanced with semantic similarity
        """
        if not self.cache:
            return None
            
        try:
            # Get all cached RAG entries from memory cache
            cache_entries = self.cache.memory_cache
            
            question_words = set(question.lower().split())
            
            for cache_key, entry in cache_entries.items():
                if (entry.service_type == self.service_name and 
                    "rag_query" in cache_key and 
                    self.cache._is_cache_valid(entry)):
                    
                    cached_question = entry.query_params.get("question", "")
                    cached_words = set(cached_question.lower().split())
                    
                    # Simple similarity check (could be enhanced)
                    if len(question_words) > 0 and len(cached_words) > 0:
                        overlap = len(question_words.intersection(cached_words))
                        similarity = overlap / max(len(question_words), len(cached_words))
                        
                        # If 70% word overlap, consider it similar enough
                        if similarity >= 0.7:
                            logger.debug(f"Found similar cached query (similarity: {similarity:.2f})")
                            return entry.data
            
        except Exception as e:
            logger.warning(f"Error checking for similar queries: {e}")
        
        return None
    
    def _get_cached_or_execute(self, method_name: str, params: Dict[str, Any], 
                              execute_func, query_type: str = ""):
        """
        Generic caching wrapper for RAG service methods with similarity checking
        """
        if not self.cache:
            return execute_func()
        
        # Try exact cache match first
        cached_result, is_hit = self.cache.get(
            self.service_name, method_name, params, query_type
        )
        
        if is_hit:
            logger.info(f"✓ Cache HIT for {method_name}: {params.get('question', 'N/A')[:50]}...")
            return cached_result
        
        # For RAG queries, check for similar questions
        if method_name == "rag_query":
            question = params.get('question', '')
            similar_result = self._find_similar_cached_query(question, query_type)
            if similar_result:
                logger.info(f"✓ Similar cache HIT for {method_name}: {question[:50]}...")
                return similar_result
        
        # Execute function and cache result
        try:
            logger.info(f"⚡ Executing {method_name}: {params.get('question', 'N/A')[:50]}...")
            result = execute_func()
            
            # Cache the result
            self.cache.set(self.service_name, method_name, params, result, query_type)
            logger.info(f"✓ Cached result for {method_name}")
            
            return result
            
        except Exception as e:
            logger.error(f"✗ Error in {method_name}: {str(e)}")
            raise
        
    def query(self, question: str, query_type: str = "knowledge") -> Dict[str, Any]:
        """Query the knowledge base with intelligent caching"""
        if not self.qa_chain:
            raise ValueError("QA chain not initialized. Call initialize_qa_chain() first.")
        
        def execute_query():
            logger.info(f"Processing query: {question}")
            
            try:
                response = self.qa_chain.invoke({"query": question})
                
                result = {
                    "question": question,
                    "answer": response["result"],
                    "source_documents": []
                }
                
                for doc in response.get("source_documents", []):
                    source_info = {
                        "file_name": doc.metadata.get("file_name", "Unknown"),
                        "source": doc.metadata.get("source", "Unknown"),
                        "content_preview": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
                    }
                    result["source_documents"].append(source_info)
                
                logger.info(f"Query processed successfully. Found {len(result['source_documents'])} source documents.")
                return result
                
            except Exception as e:
                logger.error(f"Error processing query: {str(e)}")
                raise
        
        # Use caching wrapper with normalized question
        normalized_question = question.lower().strip()
        cache_params = {"question": normalized_question}
        
        return self._get_cached_or_execute("rag_query", cache_params, execute_query, query_type)
    
    def invalidate_cache(self, question: str = None) -> int:
        """Invalidate cached RAG data for a specific question or all RAG queries"""
        if not self.cache:
            return 0
        
        if question:
            # For specific question invalidation, we'd need more sophisticated matching
            # For now, clear all RAG cache
            count = self.cache.invalidate_service(self.service_name, "rag_query")
            logger.info(f"Invalidated RAG cache for question: {question[:50]}...")
            return count
        else:
            return self.cache.invalidate_service(self.service_name)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        if not self.cache:
            return {"caching": "disabled"}
        return self.cache.get_cache_stats()
    
    def clear_cache(self) -> None:
        """Clear all RAG cache entries"""
        if self.cache:
            self.cache.invalidate_service(self.service_name)
            logger.info("RAG service cache cleared")


def create_rag_service(
    input_files_path: str = r"C:\Temp\_Dev\Langchain-Agents\agents-trading-investing\backend\data\sample_docs",
    recreate_vector_db: bool = False
) -> RAGService:
    """Factory function to create and initialize RAG service"""
    logger.info("Creating RAG service...")
    
    rag_service = RAGService(input_files_path=input_files_path)
    rag_service.create_vector_store(recreate_vector_db=recreate_vector_db)
    rag_service.initialize_qa_chain()
    
    logger.info("RAG service created successfully")
    return rag_service


if __name__ == "__main__":
    input_files_path = r"C:\Users\RusselAlfeche\OneDrive\Books - Trading and Investing"
    
    try:
        # Create RAG service
        rag = create_rag_service(
            input_files_path=input_files_path,
            recreate_vector_db=True
        )
        
        test_queries = [
            "What is the current market sentiment?",
            "How should I analyze financial statements?",
            "What are the key trading indicators?",
            "Explain risk management strategies"
        ]
        
        for query in test_queries:
            print(f"\n{'='*50}")
            print(f"Query: {query}")
            print('='*50)
            
            result = rag.query(query)
            print(f"Answer: {result['answer']}")
            
            if result['source_documents']:
                print(f"\nSources ({len(result['source_documents'])}):")
                for i, doc in enumerate(result['source_documents'], 1):
                    print(f"{i}. {doc['file_name']}")
                    print(f"   Preview: {doc['content_preview']}")
        
    except Exception as e:
        logger.error(f"Error running RAG service: {str(e)}")
