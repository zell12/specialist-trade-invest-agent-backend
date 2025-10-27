import os
import logging
import warnings
from typing import List, Optional, Dict, Any
from pathlib import Path
from tqdm import tqdm
import time
import pickle
import hashlib

# LangChain imports
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    DirectoryLoader,
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

# Only suppress loggers, NOT warnings (so WarningDetector can catch them)
logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("pypdf.generic._data_structures").setLevel(logging.ERROR)
logging.getLogger("pypdf._page_labels").setLevel(logging.ERROR)


class WarningDetector:
    """Captures warnings to detect problematic PDFs early"""
    
    def __init__(self):
        self.problematic_warnings = []
        self.warning_patterns = [
            "Invalid Elementary Object",
            "PdfReadError", 
            "Could not reliably determine page label",
            "corrupt",
            "malformed",
            "xref table",
            "startxref"
        ]
        self.original_showwarning = None
    
    def __enter__(self):
        warnings.resetwarnings()
        self.original_showwarning = warnings.showwarning
        warnings.showwarning = self._capture_warning
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.original_showwarning:
            warnings.showwarning = self.original_showwarning
        
        warnings.filterwarnings("ignore", category=UserWarning, module="pypdf")
        warnings.filterwarnings("ignore", message=".*Invalid Elementary Object.*")
        warnings.filterwarnings("ignore", message=".*Could not reliably determine page label.*")
    
    def _capture_warning(self, message, category, filename, lineno, file=None, line=None):
        warning_text = str(message)
        
        if any(pattern.lower() in warning_text.lower() for pattern in self.warning_patterns):
            self.problematic_warnings.append(warning_text)
            logger.debug(f"Detected problematic warning: {warning_text}")
        pass
    
    def has_problematic_warnings(self) -> bool:
        return len(self.problematic_warnings) > 0


class CustomPDFLoader:
    """Custom PDF loader that skips immediately on problematic warnings"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
    
    def load(self) -> List[Document]:
        """Load PDF and skip immediately if problematic warnings detected"""
        try:
            with WarningDetector() as detector:
                loader = PyPDFLoader(self.file_path)
                
                documents = []
                for i, doc in enumerate(loader.lazy_load()):
                    if detector.has_problematic_warnings():
                        logger.warning(f"⚠ Skipping {Path(self.file_path).name} - detected problematic warnings at page {i+1}")
                        return []
                    
                    documents.append(doc)
                    
                    if i > 0 and i % 5 == 0 and detector.has_problematic_warnings():
                        logger.warning(f"⚠ Skipping {Path(self.file_path).name} - detected issues at page {i+1}")
                        return []
                
                if documents:
                    logger.info(f"✓ Loaded {len(documents)} pages from {Path(self.file_path).name}")
                
                return documents
                
        except Exception as e:
            error_msg = str(e).lower()
            
            if any(pattern in error_msg for pattern in [
                "invalid elementary object",
                "pdfreadeerror", 
                "corrupt",
                "invalid pdf",
                "malformed"
            ]):
                logger.warning(f"⚠ Skipping corrupted PDF {Path(self.file_path).name}: {str(e)}")
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
        chunk_overlap: int = 100,
        batch_size: int = 50,
        max_retries: int = 3
    ):
        self.input_files_path = Path(input_files_path)
        self.persist_directory = persist_directory
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.batch_size = batch_size
        self.max_retries = max_retries
        
        # Progress tracking files
        self.progress_dir = Path(persist_directory) / "progress"
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        
        # Enhanced progress tracking
        self.documents_file = self.progress_dir / "documents.pkl"
        self.chunks_file = self.progress_dir / "chunks.pkl"
        self.progress_file = self.progress_dir / "progress.txt"
        self.config_file = self.progress_dir / "config.json"
        
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
    
    def load_documents(self) -> List[Document]:
        """Load documents with caching and change detection"""
        
        # Check if we can use cached documents
        if not self._config_changed():
            cached_docs = self._load_documents()
            if cached_docs is not None:
                logger.info("Using cached documents (no changes detected)")
                return cached_docs
        else:
            logger.info("Configuration or directory changed, reloading documents")
        
        # Load documents fresh
        all_documents = []
        
        if not self.input_files_path.exists():
            logger.error(f"Input files path does not exist: {self.input_files_path}")
            return all_documents
        
        logger.info(f"Loading documents from: {self.input_files_path}")
        
        # Get file list
        files = self._get_file_list()
        if not files:
            logger.warning("No supported files found")
            return all_documents
        
        logger.info(f"Found {len(files)} files to process")
        
        # Simple loaders
        loaders = {
            '.txt': TextLoader,
            '.pdf': CustomPDFLoader,
            '.docx': Docx2txtLoader,
            '.csv': CSVLoader
        }
        
        # Statistics
        success_count = 0
        error_count = 0
        skipped_count = 0
        
        # Process files with progress bar
        with tqdm(files, desc="Loading documents", unit="file") as pbar:
            for file_path in pbar:
                file_extension = file_path.suffix.lower()
                
                # Update progress bar
                pbar.set_postfix({
                    'file': file_path.name[:15] + '...' if len(file_path.name) > 15 else file_path.name,
                    'success': success_count,
                    'errors': error_count,
                    'skipped': skipped_count
                })
                
                if file_extension in loaders:
                    try:
                        loader_class = loaders[file_extension]
                        loader = loader_class(str(file_path))
                        file_docs = loader.load()
                        
                        if file_docs:
                            # Add metadata
                            for doc in file_docs:
                                doc.metadata.update({
                                    'source': str(file_path),
                                    'file_name': file_path.name,
                                    'file_type': file_extension,
                                    'file_size': file_path.stat().st_size
                                })

                            all_documents.extend(file_docs)
                            success_count += 1
                        else:
                            skipped_count += 1
                        
                    except Exception as e:
                        error_count += 1
                        logger.error(f"✗ Failed to load {file_path.name}: {str(e)}")
                else:
                    skipped_count += 1
                    
        # Final statistics
        logger.info(f"Document loading complete:")
        logger.info(f"  ✓ Successfully loaded: {success_count} files")
        logger.info(f"  ✗ Errors: {error_count} files")
        logger.info(f"  ⚠ Skipped: {skipped_count} files")
        logger.info(f"  📄 Total documents: {len(all_documents)}")
        
        # Save documents and configuration
        self._save_documents(all_documents)
        self._save_config()
        
        return all_documents
    
    def create_vector_store(self, force_recreate: bool = False, resume: bool = True) -> None:
        """Create or update the vector store with enhanced resume capability"""
        
        # Check if vector store already exists and we're not forcing recreation
        if not force_recreate and Path(self.persist_directory).exists():
            try:
                logger.info("Loading existing vector store...")
                self.vector_store = Chroma(
                    persist_directory=self.persist_directory,
                    embedding_function=self.embeddings
                )
                # Check if it's actually populated by trying a similarity search
                try:
                    # Try to get some documents to check if vector store has content
                    test_results = self.vector_store.similarity_search("test", k=1)
                    if test_results:
                        logger.info(f"Vector store loaded successfully with existing embeddings.")
                        self._clear_progress()  # Clear any old progress files
                        return
                    else:
                        logger.info("Vector store exists but appears empty. Creating new one...")
                except Exception:
                    logger.info("Vector store exists but appears empty. Creating new one...")
            except Exception as e:
                logger.warning(f"Failed to load existing vector store: {e}. Creating new one...")
        
        # Clear progress if force recreating
        if force_recreate:
            self._clear_progress()
        
        logger.info("Creating new vector store...")
        
        # Try to resume from saved chunks first
        texts = None
        if resume and not self._config_changed():
            texts = self._load_chunks()
            if texts:
                logger.info("Resuming with cached chunks")
        
        # If no saved chunks or config changed, process documents
        if texts is None:
            # Load documents (will use cache if possible)
            documents = self.load_documents()
            
            if not documents:
                logger.warning("No documents found to create vector store.")
                return

            # Split documents into chunks
            logger.info("Splitting documents into chunks...")
            texts = []
            
            with tqdm(documents, desc="Splitting documents", unit="doc") as pbar:
                for doc in pbar:
                    try:
                        chunks = self.text_splitter.split_documents([doc])
                        texts.extend(chunks)
                        pbar.set_postfix({'total_chunks': len(texts)})
                    except Exception as e:
                        logger.warning(f"Error splitting document {doc.metadata.get('file_name', 'unknown')}: {str(e)}")
            
            logger.info(f"Created {len(texts)} text chunks")
            
            # Save chunks immediately for resuming (before embeddings start)
            self._save_chunks(texts)
            logger.info("Chunks saved for resume capability")
        
        if not texts:
            logger.warning("No text chunks created.")
            return
        
        # Calculate batches
        total_batches = (len(texts) + self.batch_size - 1) // self.batch_size
        
        # Check for existing progress
        start_batch, saved_total = self._load_progress()
        if start_batch > 0 and saved_total == total_batches:
            logger.info(f"Resuming embeddings from batch {start_batch + 1}/{total_batches}")
        else:
            start_batch = 0
            logger.info(f"Starting fresh - processing {len(texts)} chunks in {total_batches} batches of {self.batch_size}")
        
        # Create vector store with batch processing
        logger.info("Creating embeddings and vector store...")
        try:
            os.makedirs(self.persist_directory, exist_ok=True)
            
            # Initialize vector store with first batch if starting fresh
            if start_batch == 0:
                first_batch = texts[:self.batch_size]
                logger.info(f"Creating initial vector store with batch 1/{total_batches} ({len(first_batch)} chunks)")
                
                retry_count = 0
                while retry_count < self.max_retries:
                    try:
                        self.vector_store = Chroma.from_documents(
                            documents=first_batch,
                            persist_directory=self.persist_directory,
                            embedding=self.embeddings
                        )
                        break
                    except Exception as e:
                        retry_count += 1
                        logger.warning(f"Retry {retry_count}/{self.max_retries} for initial batch: {str(e)}")
                        if retry_count >= self.max_retries:
                            raise
                        time.sleep(2 ** retry_count)
                
                self._save_progress(0, total_batches)
                start_batch = 1
            else:
                # Load existing vector store for resuming
                self.vector_store = Chroma(
                    persist_directory=self.persist_directory,
                    embedding_function=self.embeddings
                )
            
            # Process remaining batches
            with tqdm(range(start_batch, total_batches), desc="Processing batches", initial=start_batch, total=total_batches) as pbar:
                for batch_idx in pbar:
                    start_idx = batch_idx * self.batch_size
                    end_idx = min(start_idx + self.batch_size, len(texts))
                    batch = texts[start_idx:end_idx]
                    
                    pbar.set_postfix({
                        'batch': f"{batch_idx + 1}/{total_batches}",
                        'chunks': f"{end_idx}/{len(texts)}"
                    })
                    
                    retry_count = 0
                    while retry_count < self.max_retries:
                        try:
                            self.vector_store.add_documents(batch)
                            break
                        except Exception as e:
                            retry_count += 1
                            logger.warning(f"Retry {retry_count}/{self.max_retries} for batch {batch_idx + 1}: {str(e)}")
                            if retry_count >= self.max_retries:
                                logger.error(f"Failed to process batch {batch_idx + 1} after {self.max_retries} retries")
                                self._save_progress(batch_idx, total_batches)
                                raise
                            time.sleep(2 ** retry_count)
                    
                    # Save progress after each successful batch
                    self._save_progress(batch_idx, total_batches)
                    
                    # Small delay to avoid rate limiting
                    time.sleep(0.1)
            
            logger.info("Vector store created successfully.")
            self._clear_progress()  # Clear progress files on successful completion
            
        except Exception as e:
            logger.error(f"Error creating vector store: {str(e)}")
            logger.info("Progress saved. You can resume by running again with resume=True")
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
        
    def query(self, question: str) -> Dict[str, Any]:
        """Query the knowledge base"""
        if not self.qa_chain:
            raise ValueError("QA chain not initialized. Call initialize_qa_chain() first.")
        
        logger.info(f"Processing query: {question}")
        
        try:
            response = self.qa_chain({"query": question})
            
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


def create_rag_service(
    input_files_path: str = r"C:\Temp\_Dev\Langchain-Agents\agents-trading-investing\backend\data\sample_docs",
    force_recreate: bool = False,
    resume: bool = True,
    batch_size: int = 50
) -> RAGService:
    """Factory function to create and initialize RAG service with enhanced resume capability"""
    logger.info("Creating RAG service...")
    
    rag_service = RAGService(
        input_files_path=input_files_path,
        batch_size=batch_size
    )
    rag_service.create_vector_store(force_recreate=force_recreate, resume=resume)
    rag_service.initialize_qa_chain()
    
    logger.info("RAG service created successfully")
    return rag_service


if __name__ == "__main__":
    input_files_path = r"C:\Users\RusselAlfeche\OneDrive\Books - Trading and Investing"
    
    try:
        # Resume from where it left off - will NOT reload documents
        rag = create_rag_service(
            input_files_path=input_files_path,
            force_recreate=False,  # Don't recreate, try to resume
            resume=True,           # Enable resume capability
            batch_size=50          # Smaller batch size to avoid token limits
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