#!/usr/bin/env python3
"""
Local test runner - runs tests against remote RunPod API with human-friendly output.
No heavy dependencies required (no sentence-transformers).

Supports tool calling for realm-specific tests using staging network.
"""
import json
import requests
import glob
import os
import sys
import subprocess
import traceback

API_URL = os.environ.get('API_URL', 'https://geister-api.realmsgos.dev ')
REALM_NETWORK = os.environ.get('REALM_NETWORK', 'staging')
REALM_FOLDER = os.environ.get('REALM_FOLDER', '.')

def load_tests(tests_dir="tests"):
    """Load test cases from local JSON files"""
    test_cases = []
    json_files = sorted(glob.glob(os.path.join(tests_dir, "test_tools_*.json")))
    
    for file_path in json_files:
        with open(file_path, 'r') as f:
            test_case = json.load(f)
            test_case['file'] = os.path.basename(file_path)
            test_cases.append(test_case)
    
    return test_cases

def setup_staging_network():
    """Set up staging network for realm queries"""
    try:
        result = subprocess.run(
            ["realms", "network", "set", "staging"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Warning: Could not set staging network: {e}")
        traceback.print_exc()
        return False

def ask_api(question, use_tools=False):
    """Call the Ashoka API"""
    try:
        if use_tools:
            # Use tool calling endpoint
            response = requests.post(
                f"{API_URL}/api/ask-with-tools",
                json={
                    "question": question,
                    "realm_folder": REALM_FOLDER,
                    "network": REALM_NETWORK
                },
                timeout=120
            )
        else:
            response = requests.post(
                f"{API_URL}/api/ask",
                json={"question": question},
                timeout=120
            )
        
        if response.status_code == 200:
            data = response.json()
            answer = data.get('answer', '')
            tools_used = data.get('tools_used', False)
            return answer, tools_used
        else:
            return f"[Error: HTTP {response.status_code}]", False
    except Exception as e:
        traceback.print_exc()
        return f"[Error: {str(e)}]", False

def print_box(title, content, width=70):
    """Print content in a nice box"""
    print(f"┌{'─' * (width-2)}┐")
    print(f"│ {title:<{width-4}} │")
    print(f"├{'─' * (width-2)}┤")
    
    # Wrap content
    words = content.split()
    lines = []
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 <= width - 4:
            current_line += (" " if current_line else "") + word
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    
    for line in lines:
        print(f"│ {line:<{width-4}} │")
    
    print(f"└{'─' * (width-2)}┘")

def main():
    print("\n" + "═" * 70)
    print("  🧪 ASHOKA LOCAL TEST RUNNER")
    print(f"  📡 API: {API_URL}")
    print(f"  🌐 Network: {REALM_NETWORK}")
    print("═" * 70 + "\n")
    
    # Set up staging network for tool calls
    print("🔧 Setting up staging network...")
    if setup_staging_network():
        print("   ✅ Staging network configured\n")
    else:
        print("   ⚠️  Could not set staging network (tool calls may fail)\n")
    
    tests = load_tests()
    
    print(f"📂 Found {len(tests)} tests to run")
    print()
    
    for i, test in enumerate(tests, 1):
        # Check if test needs tool calling
        needs_tools = "using tools" in test.get('ashoka_instructions', '').lower()
        
        print(f"\n{'─' * 70}")
        print(f"TEST {i}/{len(tests)}: {test['name']}")
        print(f"File: {test['file']}")
        if needs_tools:
            print(f"Mode: 🔧 TOOL CALLING (realm data query)")
        else:
            print(f"Mode: 💬 GENERIC (no tools)")
        print(f"{'─' * 70}\n")
        
        print(f"❓ QUESTION:")
        print(f"   {test['user_prompt']}\n")
        
        print(f"📝 EXPECTED ANSWER:")
        print(f"   {test['expected_answer']}\n")
        
        print(f"⏳ Asking Ashoka{'  (with tools)' if needs_tools else ''}...")
        answer, tools_used = ask_api(test['user_prompt'], use_tools=needs_tools)
        
        print(f"\n🤖 ACTUAL ANSWER{' (tools used ✓)' if tools_used else ''}:")
        print(f"{'─' * 50}")
        # Print answer with nice wrapping
        words = answer.split()
        line = ""
        for word in words:
            if len(line) + len(word) + 1 <= 68:
                line += (" " if line else "") + word
            else:
                print(f"   {line}")
                line = word
        if line:
            print(f"   {line}")
        print(f"{'─' * 50}")
        print(f"   ({len(answer)} characters)")
        
        print()
    
    print("\n" + "═" * 70)
    print("  ✅ TESTS COMPLETE")
    print("═" * 70 + "\n")

if __name__ == "__main__":
    main()
