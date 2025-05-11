import argparse
import logging
import os
import pathlib
import sys
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
import log, onenote, onenote_auth, pipeline

from onenote_dump import convert, log, onenote, onenote_auth, pipeline
from onenote_dump.interactor import OneNoteInteractor

# MCP Imports - Refactored for FastMCP
from mcp.server.fastmcp.server import FastMCP, Context

# --- Global MCP Application and Tool Definitions ---

# Pydantic model for dump_notebook arguments for MCP
class DumpNotebookArgs(BaseModel):
    notebook_name: str
    output_dir: str
    section_name: Optional[str] = None
    max_pages: Optional[int] = None
    start_page: Optional[int] = None
    new_session: bool = False


mcp_app = FastMCP(
    name="OneNoteDumpServer",
    version="0.1.0",  # TODO: Get version from package if possible
    description="MCP server for listing and dumping OneNote notebooks.",
    dependencies=["pydantic"] # Example dependency
)

@mcp_app.tool(description="List available OneNote notebooks.")
def list_notebooks_mcp(ctx: Context, new_session: bool = False) -> List[Dict[str, Any]]:
    """MCP tool to list OneNote notebooks."""
    ctx.info(f"Executing list_notebooks_mcp with new_session={new_session}")
    interactor = OneNoteInteractor() # Removed logger_instance
    try:
        notebooks = interactor.list_notebooks(new_session=new_session)
        ctx.info(f"Found {len(notebooks)} notebooks.")
        return notebooks
    except Exception as e:
        ctx.error(f"Error listing notebooks: {e}", exc_info=True)
        # Re-raise or return an MCP-compatible error structure
        # For now, re-raising might terminate the server or be caught by FastMCP
        raise

@mcp_app.tool(description="Dump a OneNote notebook to markdown.")
def dump_notebook_mcp(ctx: Context, args: DumpNotebookArgs) -> Dict[str, Any]:
    """MCP tool to dump a OneNote notebook."""
    ctx.info(f"Executing dump_notebook_mcp with args: {args}")
    interactor = OneNoteInteractor() # Removed logger_instance
    try:
        result = interactor.dump_notebook(
            notebook_name=args.notebook_name,
            output_dir=args.output_dir,
            section_name=args.section_name,
            max_pages=args.max_pages,
            start_page=args.start_page,
            new_session=args.new_session
        )
        ctx.info(f"Dumped notebook '{args.notebook_name}' successfully.")
        return result
    except Exception as e:
        ctx.error(f"Error dumping notebook {args.notebook_name}: {e}", exc_info=True)
        raise

# --- MCP Server Function --- 

def run_mcp_server():
    """Starts the MCP server mode over stdio."""
    # Logging is configured by FastMCP internally for its operations.
    # The tools (list_notebooks_mcp, dump_notebook_mcp) use ctx.info/error.
    print("Starting MCP server mode over stdio...", file=sys.stderr) # Basic stderr info
    try:
        mcp_app.run(transport="stdio")
    except Exception as e:
        # Log to stderr if server run fails catastrophically
        print(f"MCP server failed: {e}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

# --- CLI Argument Parsing and Main Execution ---

logger = logging.getLogger() # Standard logger for non-MCP mode

def main():
    parser = argparse.ArgumentParser(description="Dumps OneNote notebooks to markdown.")
    parser.add_argument("--settings", help="Path to the settings file (settings.json).", default="settings.json")
    parser.add_argument("--verbose", "-v", help="Enable verbose logging.", action="store_true")
    parser.add_argument("--new-session", "-n", help="Ignore saved session and re-authenticate.", action="store_true")
    parser.add_argument("--output-dir", "-o", help="Output directory for the dump.", default="output")
    parser.add_argument("--max-pages", type=int, help="Maximum number of pages to dump per section.")
    parser.add_argument("--start-page", type=int, help="Page number to start dumping from (1-indexed).")
    parser.add_argument("--mcp", action="store_true", help="Run as MCP server over stdio.")

    subparsers = parser.add_subparsers(dest="command", help="Available commands.")

    list_parser = subparsers.add_parser("list", help="List available notebooks.")

    dump_parser = subparsers.add_parser("dump", help="Dump a specific notebook.")
    dump_parser.add_argument("notebook_name", help="Name of the notebook to dump.")
    dump_parser.add_argument("--section-name", help="Name of the specific section to dump.")

    args = parser.parse_args()

    if args.mcp:
        # MCP Server Mode
        run_mcp_server()
    else:
        # Standard CLI operation
        log_level = logging.DEBUG if args.verbose else logging.INFO
        log.setup_logging(log_level)

        interactor = OneNoteInteractor(verbose=args.verbose, logger_instance=logger)

        start_time = time.time()
        if args.command == "list":
            logger.info("Listing notebooks...")
            notebooks = interactor.list_notebooks()
            if notebooks:
                logger.info("Found notebooks:")
                for nb in notebooks:
                    logger.info(f"- {nb['displayName']}")
            else:
                logger.info("No notebooks found.")
        elif args.command == "dump":
            logger.info(f"Dumping notebook: {args.notebook_name}")
            interactor.dump_notebook(
                notebook_name=args.notebook_name,
                output_dir=args.output_dir,
                section_name=args.section_name,
                max_pages=args.max_pages,
                start_page=args.start_page,
                new_session=args.new_session
            )
        else:
            parser.print_help()
            sys.exit(1)
        
        end_time = time.time()
        logger.info(f"Operation completed in {end_time - start_time:.2f} seconds.")

if __name__ == "__main__":
    main()
