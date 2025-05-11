import logging
import time
from datetime import timedelta
from typing import Optional, Dict, Any, Generator, List, Union
from functools import partial

import requests
from requests import exceptions as requests_exceptions
from tenacity import retry, retry_if_exception, wait_exponential, RetryCallState

BASE_URL = "https://graph.microsoft.com/v1.0/me/onenote/"

logger = logging.getLogger(__name__)

MIN_RETRY_WAIT = timedelta(minutes=1).total_seconds()


class NotebookNotFound(Exception):
    def __init__(self, name: str, s: Optional[requests.Session] = None, logger_instance: Optional[logging.Logger] = None):
        effective_logger = logger_instance or logger
        msg = f'Notebook "{name}" not found. '
        if s:
            msg += self._possible_notebooks(s, logger_instance=effective_logger)
        super().__init__(msg)

    @staticmethod
    def _possible_notebooks(s: requests.Session, logger_instance: Optional[logging.Logger] = None) -> str:
        effective_logger = logger_instance or logger
        notebooks_data = []
        try:
            notebooks_data = get_notebooks(s, logger_instance=effective_logger)
            if isinstance(notebooks_data, list):
                names = [n.get("displayName", "Unknown Notebook") for n in notebooks_data]
                if names:
                    return "Maybe:\n" + "\n".join(names) + "\n"
            effective_logger.debug("No possible notebook names found or unexpected format.")
            return "Possible notebooks could not be determined."
        except Exception as e:
            effective_logger.error(f"Error fetching possible notebooks: {e}", exc_info=True)
            return "Possible notebooks unknown due to an error."


def get_notebook_pages(s: requests.Session, notebook_display_name: str, section_display_name: Optional[str], logger_instance: Optional[logging.Logger] = None) -> Generator[Dict[str, Any], None, None]:
    effective_logger = logger_instance or logger
    effective_logger.debug(f"Getting pages for notebook '{notebook_display_name}', section '{section_display_name}'")
    notebooks = get_notebooks(s, logger_instance=effective_logger)
    notebook = find_notebook(notebooks, notebook_display_name, logger_instance=effective_logger)
    if notebook is None:
        raise NotebookNotFound(notebook_display_name, s, logger_instance=effective_logger)
    yield from get_pages(s, notebook, section_display_name, logger_instance=effective_logger)


def get_notebooks(s: requests.Session, logger_instance: Optional[logging.Logger] = None) -> List[Dict[str, Any]]:
    effective_logger = logger_instance or logger
    effective_logger.debug("Fetching all notebooks.")
    response_json = _get_json(s, BASE_URL + "notebooks", logger_instance=effective_logger)
    if isinstance(response_json, dict) and "value" in response_json and isinstance(response_json["value"], list):
        return response_json["value"]
    elif isinstance(response_json, list):
        return response_json
    effective_logger.warning(f"Unexpected format for notebooks response: {type(response_json)}. Expected dict with 'value' or list.")
    return []


def find_notebook(notebooks: List[Dict[str, Any]], display_name: str, logger_instance: Optional[logging.Logger] = None) -> Optional[Dict[str, Any]]:
    for notebook in notebooks:
        if notebook.get("displayName") == display_name:
            return notebook
    return None


def get_sections(s: requests.Session, parent: Dict[str, Any], section_display_name: Optional[str], logger_instance: Optional[logging.Logger] = None) -> Generator[Dict[str, Any], None, None]:
    effective_logger = logger_instance or logger
    effective_logger.debug(f"Getting sections for parent '{parent.get('displayName', 'Unknown Parent')}', target section '{section_display_name}'")
    sections_url = parent.get("sectionsUrl")
    if sections_url:
        sections_data = _get_json(s, sections_url, logger_instance=effective_logger)
        if isinstance(sections_data, dict) and "value" in sections_data:
            for section in sections_data["value"]:
                if section_display_name and section.get("displayName") != section_display_name:
                    continue
                yield section
        else:
            effective_logger.warning(f"Unexpected sections data format from {sections_url}")

    section_groups_url = parent.get("sectionGroupsUrl")
    if section_groups_url:
        section_groups_data = _get_json(s, section_groups_url, logger_instance=effective_logger)
        if isinstance(section_groups_data, dict) and "value" in section_groups_data:
            for section_group in section_groups_data["value"]:
                yield from get_sections(s, section_group, section_display_name, logger_instance=effective_logger)
        else:
            effective_logger.warning(f"Unexpected section groups data format from {section_groups_url}")


def get_pages(s: requests.Session, notebook_or_section: Dict[str, Any], section_display_name_filter: Optional[str], logger_instance: Optional[logging.Logger] = None) -> Generator[Dict[str, Any], None, None]:
    effective_logger = logger_instance or logger
    if 'pagesUrl' not in notebook_or_section:
        effective_logger.debug(f"Getting pages for notebook '{notebook_or_section.get('displayName', 'Unnamed Notebook')}', filtering by section '{section_display_name_filter if section_display_name_filter else 'all sections'}'")
        source_iterator = get_sections(s, notebook_or_section, section_display_name_filter, logger_instance=effective_logger)
    else:
        effective_logger.debug(f"Getting pages for section '{notebook_or_section.get('displayName', 'Unnamed Section')}'")
        source_iterator = iter([notebook_or_section])

    for section_like_item in source_iterator:
        url = section_like_item.get("pagesUrl")
        page_counter = 0
        while url:
            effective_logger.debug(f"Fetching pages from URL: {url} for section '{section_like_item.get('displayName', 'N/A')}'")
            pages_data = _get_json(s, url, logger_instance=effective_logger)
            if isinstance(pages_data, dict) and "value" in pages_data:
                for page in pages_data["value"]:
                    page_counter +=1
                    effective_logger.debug(f"Yielding page {page_counter}: {page.get('title', 'Untitled Page')}")
                    yield page
                url = pages_data.get("@odata.nextLink")
            else:
                effective_logger.warning(f"Unexpected pages data format from {url}. Halting pagination for this source.")
                url = None


def get_page_content(s: requests.Session, page: Dict[str, Any], logger_instance: Optional[logging.Logger] = None) -> tuple:
    effective_logger = logger_instance or logger
    content_url = page.get("contentUrl")
    effective_logger.debug(f"Fetching page content for '{page.get('title', 'Untitled Page')}' from {content_url}")
    if not content_url:
        effective_logger.error(f"Page '{page.get('title', 'Untitled Page')}' has no contentUrl.")
        return page, b"<!-- Page has no contentUrl -->"
    return page, _get_content(s, content_url, logger_instance=effective_logger)


def get_attachment(s: requests.Session, url: str, logger_instance: Optional[logging.Logger] = None) -> bytes:
    effective_logger = logger_instance or logger
    effective_logger.debug(f"Fetching attachment from {url}")
    return _get_content(s, url, logger_instance=effective_logger)


def _get_json(s: requests.Session, url: str, logger_instance: Optional[logging.Logger] = None) -> Union[Dict[str, Any], List[Any]]:
    effective_logger = logger_instance or logger
    effective_logger.debug(f"Fetching JSON from {url}")
    response = _get(s, url, logger_instance=effective_logger)
    if response is not None:
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError as e:
            logger.error(f"JSON decode error for URL {url}: {e}")
            logger.error(f"Response text: {response.text[:500]}...") 
            raise 
    logger.error(f"_get returned None or unexpected type for URL {url}")
    return {} 


def _get_content(s: requests.Session, url: str, logger_instance: Optional[logging.Logger] = None) -> bytes:
    response = _get(s, url, logger_instance=effective_logger)
    if response is not None:
        return response.content
    logger.error(f"_get returned None or unexpected type for URL {url} when fetching content")
    return b'' 


def _is_too_many_requests_condition_only(e: BaseException) -> bool:
    return isinstance(e, requests_exceptions.HTTPError) and e.response is not None and e.response.status_code == 429


def _get(s: requests.Session, url: str, logger_instance: Optional[logging.Logger] = None) -> requests.Response:
    effective_logger = logger_instance or logger

    def _log_before_sleep_retry(retry_state: RetryCallState):
        exception = retry_state.outcome.exception()
        status_code = "N/A"
        if isinstance(exception, requests_exceptions.HTTPError) and exception.response is not None:
            status_code = exception.response.status_code
        
        effective_logger.warning(
            f"Retrying request for URL '{url}' due to {type(exception).__name__} (Status: {status_code}). "
            f"Attempt {retry_state.attempt_number}, waiting {retry_state.next_action.sleep:.2f}s..."
        )

    @retry(
        retry=retry_if_exception(_is_too_many_requests_condition_only),
        wait=wait_exponential(min=MIN_RETRY_WAIT, max=MIN_RETRY_WAIT * 10),
        before_sleep=_log_before_sleep_retry,
        reraise=True
    )
    def _inner_get(current_session: requests.Session, request_url: str):
        effective_logger.debug(f"Executing GET: {request_url}")
        r = current_session.get(request_url)
        r.raise_for_status()
        effective_logger.debug(f"GET successful: {request_url}")
        return r

    return _inner_get(s, url)
