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
    extract_proposal_id_from_focus_uri,
    format_proposal_context_for_prompt,
    _candid_extension_call_args,
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


class TestProposalContext(unittest.TestCase):
    def test_extract_proposal_id_from_focus_uri(self):
        self.assertEqual(
            extract_proposal_id_from_focus_uri("realms://voting/proposal/demo_prop_0002"),
            "demo_prop_0002",
        )
        self.assertIsNone(extract_proposal_id_from_focus_uri("realms://codex_viewer/codex/tax"))

    def test_format_proposal_context_for_prompt(self):
        text = format_proposal_context_for_prompt({
            "proposal_id": "demo_prop_0002",
            "proposal": {
                "id": "demo_prop_0002",
                "title": "Increase transport budget",
                "description": "Allocate 12% more to buses.",
                "status": "voting",
                "proposer": "demo_user",
                "votes": {"yes": 0, "no": 9, "abstain": 2},
            },
            "code": {"code": "def apply():\n    pass\n"},
        })
        self.assertIn("PROPOSAL IN FOCUS", text)
        self.assertIn("demo_prop_0002", text)
        self.assertIn("Allocate 12% more", text)
        self.assertIn("def apply():", text)

    def test_fetch_proposal_code_tool_registered(self):
        self.assertIn("fetch_proposal_code", TOOL_FUNCTIONS)
        tool_names = [t["function"]["name"] for t in REALM_TOOLS if t.get("function")]
        self.assertIn("fetch_proposal_code", tool_names)

    def test_candid_extension_call_args(self):
        args = _candid_extension_call_args(
            "voting",
            "get_proposal",
            {"proposal_id": "demo_prop_0002"},
        )
        self.assertTrue(args.startswith('("voting", "get_proposal",'))
        self.assertIn("demo_prop_0002", args)


if __name__ == "__main__":
    unittest.main()
