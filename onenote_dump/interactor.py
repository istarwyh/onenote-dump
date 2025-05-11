import logging
import sys # Added for StreamHandler
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from onenote_dump import pipeline
# Ensure NotebookNotFound is imported from core if it's defined there or used by core's methods
from onenote_dump.core import OneNoteCore, NotebookNotFound 

# Removed module-level logger, instances will manage or receive their logger

class OneNoteInteractor:
    def __init__(self, verbose: bool = False, logger_instance: Optional[logging.Logger] = None):
        """
        Initialize OneNote Interactor.
        
        Args:
            verbose: Enable verbose logging.
            logger_instance: Optional logger instance to use. If None, creates its own.
        """
        self.verbose = verbose
        
        if logger_instance:
            self.logger = logger_instance
        else:
            self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
            # Configure this logger only if it has no handlers, to avoid conflicts
            # with existing global logging configurations (e.g., from basicConfig).
            if not self.logger.handlers:
                stderr_handler = logging.StreamHandler(sys.stderr)
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                stderr_handler.setFormatter(formatter)
                self.logger.addHandler(stderr_handler)
                self.logger.propagate = False # Prevent logs from going to the root logger if we configured this one
            
            self.logger.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        
        # OneNoteCore will also need to be updated to accept logger_instance
        self.core = OneNoteCore(verbose=self.verbose, logger_instance=self.logger)
    
    def list_notebooks(self) -> List[Dict[str, Any]]:
        """List all notebooks"""
        self.logger.debug("Interactor: Listing notebooks via core")
        return self.core.get_notebooks()
    
    def search_notes(self, keyword: str) -> List[Dict[str, Any]]:
        """
        Search notes (placeholder, needs Microsoft Graph API search feature)
        
        Args:
            keyword: Search keyword
        """
        self.logger.warning("Search functionality is not implemented yet.")
        # TODO: Implement note search
        raise NotImplementedError("Search functionality not implemented yet")
    
    def get_recent_notes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent notes (placeholder, needs time-sorted API)
        
        Args:
            limit: Number of notes to return
        """
        self.logger.warning("Recent notes functionality is not implemented yet.")
        # TODO: Implement recent notes retrieval
        raise NotImplementedError("Recent notes functionality not implemented yet")
    
    def dump_notebook(self, 
                     notebook_name: str,
                     output_dir: str,
                     section_name: Optional[str] = None,
                     max_pages: Optional[int] = None, # Changed from int = 0 for clarity
                     start_page: Optional[int] = None, # Changed from int = 0 for clarity
                     new_session: bool = False) -> Dict[str, Any]:
        """
        Export notebook content to the specified directory.
        
        Args:
            notebook_name: Name of the notebook to export.
            output_dir: Output directory.
            section_name: Optional, name of the section to export.
            max_pages: Optional, maximum number of pages to export.
            start_page: Optional, page number to start exporting from (0-indexed).
            new_session: Whether to use a new session (ignore saved auth token).
        
        Returns:
            Dictionary with export results:
            - total_pages: Total pages exported.
            - duration_seconds: Export duration in seconds.
            - output_path: Path to the output directory.
        """
        if new_session:
            self.logger.info("Forcing new authentication session for core.")
            # Re-initialize core with the same logger settings
            self.core = OneNoteCore(verbose=self.verbose, new_session=True, logger_instance=self.logger)
            
        start_time = datetime.now()
        page_counter = 0 # Renamed from page_count to avoid confusion with max_pages
        pages_exported = 0
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        pipe = pipeline.Pipeline(
            self.core.session_info,
            notebook_name,
            output_path
        )
        
        self.logger.info(f"Starting dump for notebook '{notebook_name}' to '{output_dir}'")
        if section_name:
            self.logger.info(f"Targeting section: '{section_name}'")
        
        try:
            for page in self.core.get_notebook_pages(notebook_name, section_name):
                page_counter += 1
                log_msg = f'Page {page_counter}: {page.get("title", "Untitled Page")}'
                
                # Determine if page should be processed based on start_page and max_pages
                should_process = True
                if start_page is not None and page_counter <= start_page: # Pages are 1-indexed for user, start_page 0-indexed in code means skip 0 pages
                    should_process = False
                    log_msg += " [skipped due to start_page]"
                
                if should_process:
                    self.logger.info(log_msg)
                    pipe.add_page(page)
                    pages_exported += 1
                else:
                    self.logger.debug(log_msg) # Log skipped pages at debug level
                    
                if max_pages is not None and pages_exported >= max_pages:
                    self.logger.info(f"Reached max_pages limit of {max_pages}.")
                    break
                    
        except NotebookNotFound as e:
            self.logger.error(f"Notebook '{notebook_name}' not found: {e}")
            raise
        except Exception as e:
            self.logger.exception(f"An unexpected error occurred during notebook dump: {e}") # Use .exception for stack trace
            raise # Re-raise the original exception
        finally:
            pipe.done()
            
        duration = (datetime.now() - start_time).total_seconds()
        self.logger.info(f"Dump finished. Exported {pages_exported} pages in {duration:.1f} seconds.")
        
        return {
            "total_pages": pages_exported,
            "duration_seconds": duration,
            "output_path": str(output_path)
        }
    
    def create_note(self, notebook_name: str, content: str):
        """
        Create a new note (placeholder, needs write API permission).
        
        Args:
            notebook_name: Notebook name.
            content: Note content.
        """
        self.logger.warning("Create note functionality is not implemented yet.")
        # TODO: Implement note creation
        raise NotImplementedError("Create note functionality not implemented yet")
