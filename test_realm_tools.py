#!/usr/bin/env python3
"""
Unit tests for realm_tools.py

Tests tool functions without requiring external dependencies (dfx, Ollama, etc.)
"""
import json
import unittest
from unittest.mock import patch, MagicMock

from realm_tools import (
    find_objects,
    REALM_TOOLS,
    TOOL_FUNCTIONS,
    execute_tool,
)


class TestFindObjects(unittest.TestCase):
    """Tests for the find_objects tool."""

    @patch('realm_tools._run_dfx_call')
    def test_find_objects_with_params(self, mock_dfx):
        """Test find_objects builds correct Candid args with params."""
        mock_dfx.return_value = '{"success": true}'
        
        find_objects(
            class_name="User",
            params=[["id", "system"], ["status", "active"]],
            network="staging",
            realm_folder="."
        )
        
        mock_dfx.assert_called_once()
        call_args = mock_dfx.call_args
        
        # Check the Candid args format
        args = call_args.kwargs.get('args') or call_args[1].get('args')
        self.assertIn('"User"', args)
        self.assertIn('record { 0 = "id"; 1 = "system"; }', args)
        self.assertIn('record { 0 = "status"; 1 = "active"; }', args)

    @patch('realm_tools._run_dfx_call')
    def test_find_objects_without_params(self, mock_dfx):
        """Test find_objects with empty params."""
        mock_dfx.return_value = '{"success": true}'
        
        find_objects(class_name="Transfer", network="staging", realm_folder=".")
        
        mock_dfx.assert_called_once()
        call_args = mock_dfx.call_args
        args = call_args.kwargs.get('args') or call_args[1].get('args')
        
        self.assertIn('"Transfer"', args)
        self.assertIn('vec {}', args)

    @patch('realm_tools._run_dfx_call')
    def test_find_objects_method_name(self, mock_dfx):
        """Test find_objects calls correct dfx method."""
        mock_dfx.return_value = '{}'
        
        find_objects(class_name="Mandate", network="staging", realm_folder=".")
        
        call_args = mock_dfx.call_args
        method = call_args.kwargs.get('method') or call_args[1].get('method')
        self.assertEqual(method, "find_objects")


class TestToolDefinitions(unittest.TestCase):
    """Tests for tool definitions in REALM_TOOLS."""

    def test_find_objects_in_realm_tools(self):
        """Test find_objects tool is defined in REALM_TOOLS."""
        tool_names = [t['function']['name'] for t in REALM_TOOLS]
        self.assertIn('find_objects', tool_names)

    def test_find_objects_in_tool_functions(self):
        """Test find_objects is registered in TOOL_FUNCTIONS."""
        self.assertIn('find_objects', TOOL_FUNCTIONS)
        self.assertEqual(TOOL_FUNCTIONS['find_objects'], find_objects)

    def test_find_objects_tool_schema(self):
        """Test find_objects tool has correct parameter schema."""
        tool = next(t for t in REALM_TOOLS if t['function']['name'] == 'find_objects')
        params = tool['function']['parameters']
        
        self.assertIn('class_name', params['properties'])
        self.assertIn('params', params['properties'])
        self.assertEqual(params['required'], ['class_name'])
        
        # Check params is array of arrays
        params_schema = params['properties']['params']
        self.assertEqual(params_schema['type'], 'array')
        self.assertEqual(params_schema['items']['type'], 'array')


class TestExecuteTool(unittest.TestCase):
    """Tests for execute_tool dispatcher."""

    @patch('realm_tools._run_dfx_call')
    def test_execute_find_objects(self, mock_dfx):
        """Test execute_tool correctly dispatches find_objects."""
        mock_dfx.return_value = '{"success": true, "data": {"objectsList": {"objects": []}}}'
        
        result = execute_tool(
            tool_name="find_objects",
            arguments={"class_name": "User", "params": [["id", "admin"]]},
            network="staging",
            realm_folder="."
        )
        
        self.assertIn("success", result)
        mock_dfx.assert_called_once()

    def test_execute_unknown_tool(self):
        """Test execute_tool returns error for unknown tool."""
        result = execute_tool(
            tool_name="nonexistent_tool",
            arguments={},
            network="staging",
            realm_folder="."
        )
        
        self.assertIn("error", result.lower())
        self.assertIn("unknown tool", result.lower())


if __name__ == "__main__":
    unittest.main()
