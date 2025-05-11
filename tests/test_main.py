# Tests for onenote_dump.main

import unittest
from unittest.mock import patch, MagicMock, call
import argparse
import sys

# Import mcp_app directly for inspecting tool registration
from onenote_dump import main as onenote_main
from onenote_dump.main import mcp_app as global_mcp_app # For checking registered tools
# GraphApi import removed as tools now use OneNoteInteractor
from mcp.server.fastmcp.server import Context # For type hinting and mocking
# OneNoteInteractor might be needed for spec if we mock it, or its return types
from onenote_dump.interactor import OneNoteInteractor 
from onenote_dump.main import DumpNotebookArgs # Import Pydantic model for args


class TestMCPExecution(unittest.TestCase):

    @patch('sys.exit')
    @patch('argparse.ArgumentParser.parse_args')
    @patch.object(global_mcp_app, 'run') # Corrected patch target
    def test_mcp_server_invoked_with_mcp_flag(self, mock_mcp_app_run, mock_parse_args, mock_sys_exit):
        # Simulate providing '--mcp' argument
        mock_parse_args.return_value = argparse.Namespace(
            mcp=True,
            command=None, # MCP mode doesn't use a command
            settings="settings.json",
            verbose=False,
            new_session=False,
            output_dir="output",
            max_pages=None,
            start_page=None,
            # For subcommands, these would be under their respective namespaces or None
            notebook_name=None, 
            section_name=None
        )

        onenote_main.main() # Call main, this should now use the mocked global_mcp_app.run

        mock_mcp_app_run.assert_called_once_with(transport="stdio")
        # We expect sys.exit(0) to be called by main() after server runs (or mock_run completes)
        mock_sys_exit.assert_called_with(0)


    @patch('sys.exit') # Mock sys.exit to prevent test runner from exiting
    @patch('argparse.ArgumentParser.parse_args')
    @patch.object(global_mcp_app, 'run') # Corrected patch target
    def test_mcp_server_registers_tools(self, mock_mcp_app_run, mock_parse_args, mock_sys_exit):
        # Tool registration happens at module import time due to decorators.
        # We just need to inspect the global_mcp_app.
        
        # Simulate --mcp flag to make main() go down the MCP path and call run (which is mocked)
        mock_parse_args.return_value = argparse.Namespace(
            mcp=True, command=None, settings="settings.json", verbose=False, 
            new_session=False, output_dir="output", max_pages=None, start_page=None,
            notebook_name=None, section_name=None
        )

        # Access the ToolManager from the global FastMCP instance
        if hasattr(global_mcp_app, '_tool_manager'):
            registered_tool_infos = global_mcp_app._tool_manager.list_tools()
            tool_names = [info.name for info in registered_tool_infos]
            self.assertIn('list_notebooks_mcp', tool_names)
            self.assertIn('dump_notebook_mcp', tool_names)

            list_tool_info = next(t for t in registered_tool_infos if t.name == 'list_notebooks_mcp')
            self.assertEqual(list_tool_info.description, "List available OneNote notebooks.")
            dump_tool_info = next(t for t in registered_tool_infos if t.name == 'dump_notebook_mcp')
            self.assertEqual(dump_tool_info.description, "Dump a OneNote notebook to markdown.")
        else:
            self.fail("Could not access _tool_manager on FastMCP instance.")
        
        onenote_main.main() # Call main to ensure it attempts to run the (mocked) server
        mock_mcp_app_run.assert_called_once_with(transport="stdio")
        mock_sys_exit.assert_called_with(0) # Expect exit(0) after MCP run call


class TestMCPToolLogic(unittest.TestCase):

    @patch('onenote_dump.main.OneNoteInteractor')
    def test_list_notebooks_mcp_success(self, mock_interactor_class):
        mock_interactor_instance = mock_interactor_class.return_value
        mock_ctx = MagicMock(spec=Context)

        sample_notebooks = [
            {'id': 'notebook1', 'displayName': 'Notebook One'},
            {'id': 'notebook2', 'displayName': 'Notebook Two'},
        ] # Simplified based on actual return of interactor.list_notebooks
        mock_interactor_instance.list_notebooks.return_value = sample_notebooks

        # Call the tool function directly
        # list_notebooks_mcp now takes (ctx: Context, new_session: bool = False)
        returned_notebooks = onenote_main.list_notebooks_mcp(mock_ctx, new_session=False)

        mock_interactor_class.assert_called_once() # Check OneNoteInteractor was instantiated
        mock_interactor_instance.list_notebooks.assert_called_once_with(new_session=False)
        
        # The tool now directly returns the notebooks list
        self.assertEqual(returned_notebooks, sample_notebooks)
        # Logging within the tool itself might be different now, let's check main.py again for ctx.info calls.
        # list_notebooks_mcp(ctx: Context, new_session: bool = False):
        #    ctx.info(f"Executing list_notebooks_mcp with new_session={new_session}")
        #    notebooks = interactor.list_notebooks(new_session=new_session)
        #    ctx.info(f"Found {len(notebooks)} notebooks.")
        #    return notebooks
        expected_ctx_calls = [
            call.info(f"Executing list_notebooks_mcp with new_session={False}"),
            call.info(f"Found {len(sample_notebooks)} notebooks.")
        ]
        mock_ctx.method_calls.sort() # Sort calls as order of info might vary with other logs
        expected_ctx_calls.sort()
        # Check if all expected calls are in method_calls, actual calls might have more (e.g. debug)
        # For now, a direct check on these specific calls
        self.assertIn(expected_ctx_calls[0], mock_ctx.method_calls)
        self.assertIn(expected_ctx_calls[1], mock_ctx.method_calls)
        mock_ctx.error.assert_not_called()

    @patch('onenote_dump.main.OneNoteInteractor')
    def test_list_notebooks_mcp_no_notebooks(self, mock_interactor_class):
        mock_interactor_instance = mock_interactor_class.return_value
        mock_ctx = MagicMock(spec=Context)

        mock_interactor_instance.list_notebooks.return_value = [] # No notebooks

        returned_notebooks = onenote_main.list_notebooks_mcp(mock_ctx, new_session=True)

        mock_interactor_class.assert_called_once()
        mock_interactor_instance.list_notebooks.assert_called_once_with(new_session=True)
        self.assertEqual(returned_notebooks, [])
        expected_ctx_calls = [
            call.info(f"Executing list_notebooks_mcp with new_session={True}"),
            call.info(f"Found 0 notebooks.")
        ]
        mock_ctx.method_calls.sort()
        expected_ctx_calls.sort()
        self.assertIn(expected_ctx_calls[0], mock_ctx.method_calls)
        self.assertIn(expected_ctx_calls[1], mock_ctx.method_calls)
        mock_ctx.error.assert_not_called()

    @patch('onenote_dump.main.OneNoteInteractor')
    def test_list_notebooks_mcp_api_error(self, mock_interactor_class):
        mock_interactor_instance = mock_interactor_class.return_value
        mock_ctx = MagicMock(spec=Context)

        error_message = "Interactor connection failed"
        mock_interactor_instance.list_notebooks.side_effect = Exception(error_message)

        # The tool re-raises the exception, so we use assertRaises
        with self.assertRaisesRegex(Exception, error_message):
            onenote_main.list_notebooks_mcp(mock_ctx, new_session=False)

        mock_interactor_class.assert_called_once()
        mock_interactor_instance.list_notebooks.assert_called_once_with(new_session=False)
        
        # Check ctx.error was called before re-raising
        # list_notebooks_mcp(ctx: Context...):
        #   except Exception as e:
        #       ctx.error(f"Error listing notebooks: {e}", exc_info=True)
        #       raise
        mock_ctx.info.assert_called_once_with(f"Executing list_notebooks_mcp with new_session={False}")
        mock_ctx.error.assert_called_once_with(f"Error listing notebooks: {error_message}", exc_info=True)


    # --- Tests for dump_notebook_mcp --- 

    @patch('onenote_dump.main.OneNoteInteractor')
    def test_dump_notebook_mcp_success(self, mock_interactor_class):
        mock_interactor_instance = mock_interactor_class.return_value
        mock_ctx = MagicMock(spec=Context)

        args = DumpNotebookArgs(
            notebook_name="Test Notebook",
            output_dir="test_output",
            section_name="Test Section",
            max_pages=10,
            start_page=1,
            new_session=False
        )
        expected_dump_result = {"status": "success", "path": "test_output/Test Notebook"}
        mock_interactor_instance.dump_notebook.return_value = expected_dump_result

        result = onenote_main.dump_notebook_mcp(mock_ctx, args)

        mock_interactor_class.assert_called_once() # Check OneNoteInteractor was instantiated
        mock_interactor_instance.dump_notebook.assert_called_once_with(
            notebook_name=args.notebook_name,
            output_dir=args.output_dir,
            section_name=args.section_name,
            max_pages=args.max_pages,
            start_page=args.start_page,
            new_session=args.new_session
        )
        self.assertEqual(result, expected_dump_result)
        mock_ctx.info.assert_any_call(f"Executing dump_notebook_mcp with args: {args}")
        mock_ctx.info.assert_any_call(f"Dumped notebook '{args.notebook_name}' successfully.")
        mock_ctx.error.assert_not_called()

    @patch('onenote_dump.main.OneNoteInteractor')
    def test_dump_notebook_mcp_error(self, mock_interactor_class):
        mock_interactor_instance = mock_interactor_class.return_value
        mock_ctx = MagicMock(spec=Context)

        args = DumpNotebookArgs(
            notebook_name="Test Notebook Fail",
            output_dir="test_output_fail",
            new_session=True
        )
        error_message = "Failed to dump notebook"
        mock_interactor_instance.dump_notebook.side_effect = Exception(error_message)

        with self.assertRaisesRegex(Exception, error_message):
            onenote_main.dump_notebook_mcp(mock_ctx, args)

        mock_interactor_class.assert_called_once()
        mock_interactor_instance.dump_notebook.assert_called_once_with(
            notebook_name=args.notebook_name,
            output_dir=args.output_dir,
            section_name=None, # Default from DumpNotebookArgs
            max_pages=None,    # Default from DumpNotebookArgs
            start_page=None,   # Default from DumpNotebookArgs
            new_session=True
        )
        mock_ctx.info.assert_called_once_with(f"Executing dump_notebook_mcp with args: {args}")
        mock_ctx.error.assert_called_once_with(f"Error dumping notebook {args.notebook_name}: {error_message}", exc_info=True)


if __name__ == '__main__':
    unittest.main()
