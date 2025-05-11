from typing import Optional, List, Dict, Any, Generator
import logging
import sys 
from pathlib import Path
from requests import Session

from onenote_dump import onenote_auth, onenote 

class NotebookNotFound(Exception):
    pass

class OneNoteCore:
    """OneNote API Core Operations Class"""
    
    def __init__(self, verbose: bool = False, new_session: bool = False, logger_instance: Optional[logging.Logger] = None):
        """
        Initialize OneNote Core operations class.
        
        Args:
            verbose: Enable verbose logging.
            new_session: Whether to force a new authentication session.
            logger_instance: Optional logger instance to use. If None, creates its own.
        """
        self.verbose = verbose
        
        if logger_instance:
            self.logger = logger_instance
        else:
            self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
            if not self.logger.handlers: 
                stderr_handler = logging.StreamHandler(sys.stderr)
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                stderr_handler.setFormatter(formatter)
                self.logger.addHandler(stderr_handler)
                self.logger.propagate = False
            self.logger.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        
        self.logger.debug(f"Initializing OneNoteCore. Verbose: {self.verbose}, New Session: {new_session}")
        self.session = onenote_auth.get_session(new_session, logger_instance=self.logger) 
        
    def get_notebooks(self) -> List[Dict[str, Any]]:
        """Get all notebooks"""
        self.logger.debug("Core: Fetching notebooks.")
        try:
            notebooks_data = onenote.get_notebooks(self.session, logger_instance=self.logger) 
            if isinstance(notebooks_data, dict) and "value" in notebooks_data:
                return notebooks_data["value"]
            elif isinstance(notebooks_data, list): 
                return notebooks_data
            else:
                self.logger.error(f"Unexpected format for notebooks data: {type(notebooks_data)}")
                return []
        except Exception as e:
            self.logger.exception("Core: Error fetching notebooks.")
            raise
    
    def get_notebook_pages(self, 
                          notebook_name: str, 
                          section_name: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
        """
        Get all pages in a notebook.
        
        Args:
            notebook_name: Notebook name.
            section_name: Optional section name.
        
        Yields:
            Page information dictionary.
        """
        self.logger.debug(f"Core: Fetching pages for notebook '{notebook_name}', section '{section_name}'.")
        try:
            yield from onenote.get_notebook_pages(self.session, notebook_name, section_name, logger_instance=self.logger)
        except onenote.NotebookNotFound as e: 
            self.logger.error(f"Core: Notebook '{notebook_name}' not found during page fetch.")
            raise NotebookNotFound(f"Notebook '{notebook_name}' not found.") from e 
        except Exception as e:
            self.logger.exception(f"Core: Error fetching pages for notebook '{notebook_name}'.")
            raise
    
    def get_page_content(self, page: Dict[str, Any]) -> tuple:
        """
        Get page content.
        
        Args:
            page: Page information dictionary.
        
        Returns:
            (page, content) tuple.
        """
        page_title = page.get('title', 'Untitled Page')
        self.logger.debug(f"Core: Fetching content for page '{page_title}'.")
        try:
            return onenote.get_page_content(self.session, page, logger_instance=self.logger)
        except Exception as e:
            self.logger.exception(f"Core: Error fetching content for page '{page_title}'.")
            raise
    
    @property
    def session_info(self) -> Session:
        """Get current session"""
        return self.session
