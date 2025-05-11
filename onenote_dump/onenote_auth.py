import datetime
import json
import logging
import webbrowser
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from queue import Queue, Empty
from threading import Thread
from time import sleep
from typing import Optional, Dict
from urllib.parse import urlparse

from oauthlib.oauth2 import TokenExpiredError, WebApplicationClient
from requests_oauthlib import OAuth2Session

logger = logging.getLogger(__name__)

client_id = "c55c98cc-9cf9-43dc-8e84-38b60cd514b5"
scope = ["Notes.Read"]
auth_url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

redirect_uri = "http://localhost:8000/auth"

token_path = Path.home() / ".onenote-dump-token"


def get_session(new: bool = False, logger_instance: Optional[logging.Logger] = None):
    effective_logger = logger_instance or logger
    try:
        return session_from_saved_token(new, logger_instance=effective_logger)
    except (IOError, TokenExpiredError):
        effective_logger.info("Saved token not found or expired, initiating user authentication.")
        return session_from_user_auth(logger_instance=effective_logger)


def session_from_saved_token(new: bool, logger_instance: Optional[logging.Logger] = None):
    effective_logger = logger_instance or logger
    if new:
        effective_logger.info("Ignoring saved auth token.")
        effective_logger.info(
            "NOTE: To switch accounts, you may need to delete all browser "
            "cookies for login.live.com and login.microsoftonline.com."
        )
        _delete_token(logger_instance=effective_logger)
        raise TokenExpiredError("Forcing new token by user request.")
    token = _load_token(logger_instance=effective_logger)
    expires = datetime.datetime.fromtimestamp(token["expires_at"])
    if expires < datetime.datetime.now() + datetime.timedelta(minutes=5):
        effective_logger.debug("Saved token expired or will expire soon.")
        raise TokenExpiredError("Token expired or is about to expire.")
    effective_logger.debug("Successfully loaded session from saved token.")
    s = OAuth2Session(client_id, token=token)
    return s


def session_from_user_auth(logger_instance: Optional[logging.Logger] = None):
    """Get an authenticated session by having the user authorize access."""
    effective_logger = logger_instance or logger
    effective_logger.info("Starting HTTP server for auth redirect.")
    server = AuthHTTPServer(redirect_uri, logger_instance=effective_logger)
    server.start()

    sleep(1)  # Give server a moment to start

    try:
        # Create and configure the OAuth2 client
        oauth_client = WebApplicationClient(client_id)
        s = OAuth2Session(
            client=oauth_client,
            client_id=client_id,
            scope=scope,
            redirect_uri=redirect_uri,
            token_updater=lambda token: _save_token(token, logger_instance=effective_logger)
        )

        authorization_url, state = s.authorization_url(auth_url)
        effective_logger.info("Launching browser to authorize... %s", authorization_url)
        webbrowser.open(authorization_url)

        effective_logger.info("Waiting for authorization redirect from browser...")
        redirect_url = server.wait_for_auth_redirect()
        effective_logger.info("Authorization redirect received. Fetching token...")
        token = s.fetch_token(
            token_url=token_url,
            client_id=client_id,
            authorization_response=redirect_url,
            include_client_id=True,
        )
        _save_token(token, logger_instance=effective_logger)
        effective_logger.info("Successfully obtained and saved new token.")
        return s
    finally:
        effective_logger.info("Stopping AuthHTTPServer.")
        server.stop()
        effective_logger.info("AuthHTTPServer stopped.")


class _AuthServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.logger.info(f"AuthServer: GET request received for path: {self.path}")
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.server.queue.put(self.path)
        self.server.logger.info(f"AuthServer: Path '{self.path}' put into queue.")
        # Send a more user-friendly message to the browser
        message = "<html><head><title>Authentication Status</title></head><body><p>Authentication successful! You can close this tab and return to the application.</p></body></html>"
        self.wfile.write(message.encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        # Optionally, direct http.server logs to our logger if desired
        # For now, let http.server log to stderr as default or handle as needed
        # self.server.logger.debug(f"HTTP Log: {format % args}") 
        return # Suppress default http.server logging to stderr if too noisy


class AuthHTTPServer(HTTPServer):
    """Simple HTTP server to handle the authorization redirect."""

    def __init__(self, url: str, logger_instance: Optional[logging.Logger] = None):
        self.url = urlparse(url)
        self.queue = Queue()
        self.server = None
        self.logger = logger_instance or logger 
        self.logger.debug(f"AuthHTTPServer initialized for {url}")

    def start(self):
        """Start the HTTP server in a new thread."""
        self.logger.debug(
            f"Starting AuthHTTPServer on port {self.url.port}"
        )
        # Set daemon=True so the thread exits when the main program exits
        self.thread = Thread(target=self._run_server, daemon=True)
        self.thread.name = "AuthHTTPServerThread" # Assign a name for easier debugging
        self.thread.start()
        self.logger.debug("AuthHTTPServer thread started.")

    def wait_for_auth_redirect(self) -> str:
        """Wait for the authorization redirect and return the path."""
        self.logger.info(
            f"AuthServer: Waiting for redirect matching path component: '{self.url.path}'"
        )
        path = ""
        try:
            # The loop condition ensures we wait until the expected path component is found.
            # If the queue is empty, get() will block until an item is available or timeout occurs.
            while self.url.path not in path:
                self.logger.debug("AuthServer: Attempting to get path from queue...")
                # Timeout reduced for quicker debugging cycles. Original was 120s.
                # This timeout applies to a single queue.get() operation.
                path = self.queue.get(timeout=120)  # Increased timeout back to 120s
                self.logger.info(
                    f"AuthServer: Path dequeued: '{path}'. Comparing with expected: '{self.url.path}'"
                )
            self.logger.info(f"AuthServer: Matching path received: '{path}'")
            # Construct the full redirect URL, as expected by OAuth token fetching logic.
            # self.url is urlparse(redirect_uri) which contains scheme and netloc.
            # path is the path component with query parameters (e.g., /auth?code=...)
            full_redirect_url = f"{self.url.scheme}://{self.url.netloc}{path}"
            self.logger.info(f"AuthServer: Constructed full redirect URL: '{full_redirect_url}'")
            return full_redirect_url
        except Empty:  
            self.logger.error(
                f"AuthServer: Timeout (120s) waiting for auth redirect containing '{self.url.path}'. Last path from queue (if any): '{path if path else 'None'}'"
            )
            raise TimeoutError(
                f"Timeout waiting for auth redirect containing '{self.url.path}'"
            )

    def _run_server(self):
        address = ("", self.url.port)
        self.server = HTTPServer(address, _AuthServerHandler)
        self.server.queue = self.queue 
        self.server.logger = self.logger 
        self.logger.info(f"AuthHTTPServer listening on {address[0] or '0.0.0.0'}:{address[1]}")
        try:
            self.server.serve_forever()
        except Exception as e:
            self.logger.error(f"AuthHTTPServer encountered an error: {e}")
        self.logger.info("AuthHTTPServer stopped.")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def _save_token(token: Dict, logger_instance: Optional[logging.Logger] = None):
    effective_logger = logger_instance or logger
    try:
        token_path.write_text(json.dumps(token))
        effective_logger.debug("Auth token saved to %s", token_path)
    except IOError as e:
        effective_logger.error(f"Failed to save token to {token_path}: {e}")


def _load_token(logger_instance: Optional[logging.Logger] = None) -> Dict:
    effective_logger = logger_instance or logger
    try:
        token_str = token_path.read_text()
        token = json.loads(token_str)
        effective_logger.debug("Auth token loaded from %s", token_path)
        return token
    except FileNotFoundError:
        effective_logger.debug(f"Token file {token_path} not found.")
        raise 
    except (IOError, json.JSONDecodeError) as e:
        effective_logger.error(f"Failed to load or parse token from {token_path}: {e}")
        _delete_token(logger_instance=effective_logger) 
        raise IOError(f"Corrupted token file: {e}") 


def _delete_token(logger_instance: Optional[logging.Logger] = None):
    effective_logger = logger_instance or logger
    try:
        token_path.unlink()
        effective_logger.debug(f"Deleted token file {token_path}.")
    except FileNotFoundError:
        effective_logger.debug(f"Token file {token_path} not found, nothing to delete.")
    except OSError as e:
        effective_logger.error(f"Error deleting token file {token_path}: {e}")
