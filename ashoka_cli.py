#!/usr/bin/env python3
"""
Ashoka CLI - Command line interface for interacting with the Ashoka API
"""
import argparse
import json
import requests
import sys
import os
from pathlib import Path
import time
from typing import Optional, Dict, Any
import traceback

class AshokaClient:
    """Client for interacting with Ashoka API"""
    
    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make HTTP request to API"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, params=params)
            elif method.upper() == 'POST':
                response = self.session.post(url, json=data)
            elif method.upper() == 'DELETE':
                response = self.session.delete(url)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.ConnectionError:
            print(f"❌ Error: Could not connect to Ashoka API at {self.base_url}")
            print("   Make sure the API server is running (python api.py)")
            sys.exit(1)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status == 502:
                print(f"❌ API server is currently unavailable (502 Bad Gateway)")
                print(f"   The server may be restarting after a deployment. Please try again in a minute.")
            elif status == 503:
                print(f"❌ API server is temporarily unavailable (503 Service Unavailable)")
                print(f"   Please try again in a few moments.")
            elif status == 504:
                print(f"❌ API request timed out (504 Gateway Timeout)")
                print(f"   The server may be overloaded. Please try again.")
            elif status == 500:
                print(f"❌ Internal server error (500)")
                print(f"   Something went wrong on the server side.")
            elif status == 404:
                print(f"❌ API endpoint not found (404)")
            else:
                print(f"❌ HTTP Error {status}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error: {str(e)}")
            traceback.print_exc()
            sys.exit(1)
    
    def ask_question(self, question: str, user_principal: str = "", realm_principal: str = "", 
                    persona: str = "", ollama_url: str = "http://localhost:11434", 
                    realm_status: Optional[Dict] = None, stream: bool = False) -> Dict[str, Any]:
        """Ask a question to Ashoka"""
        data = {
            "question": question,
            "user_principal": user_principal,
            "realm_principal": realm_principal,
            "ollama_url": ollama_url,
            "stream": stream
        }
        
        if persona:
            data["persona"] = persona
        
        if realm_status:
            data["realm_status"] = realm_status
        
        return self._make_request("POST", "/api/ask", data)
    
    def get_suggestions(self, user_principal: str = "", realm_principal: str = "", 
                       persona: str = "", ollama_url: str = "http://localhost:11434") -> Dict[str, Any]:
        """Get contextual suggestions"""
        params = {
            "user_principal": user_principal,
            "realm_principal": realm_principal,
            "ollama_url": ollama_url
        }
        
        if persona:
            params["persona"] = persona
        
        return self._make_request("GET", "/suggestions", params=params)
    
    def list_personas(self) -> Dict[str, Any]:
        """List all available personas"""
        return self._make_request("GET", "/api/personas")
    
    def get_persona(self, persona_name: str) -> Dict[str, Any]:
        """Get specific persona details"""
        return self._make_request("GET", f"/api/personas/{persona_name}")
    
    def create_persona(self, name: str, content: str) -> Dict[str, Any]:
        """Create a new persona"""
        data = {"name": name, "content": content}
        return self._make_request("POST", "/api/personas", data)
    
    def delete_persona(self, persona_name: str) -> Dict[str, Any]:
        """Delete a persona"""
        return self._make_request("DELETE", f"/api/personas/{persona_name}")
    
    def get_realm_status(self, realm_principal: str) -> Dict[str, Any]:
        """Get realm status"""
        return self._make_request("GET", f"/api/realm-status/{realm_principal}")
    
    def fetch_realm_status(self, realm_principal: str, realm_url: str = "", network: str = "ic") -> Dict[str, Any]:
        """Fetch and store realm status"""
        data = {
            "realm_principal": realm_principal,
            "network": network
        }
        if realm_url:
            data["realm_url"] = realm_url
        
        return self._make_request("POST", "/api/realm-status/fetch", data)
    
    def get_all_realms_status(self) -> Dict[str, Any]:
        """Get status for all tracked realms"""
        return self._make_request("GET", "/api/realm-status/all")
    
    def health_check(self) -> Dict[str, Any]:
        """Check API health"""
        return self._make_request("GET", "/")


def format_json_output(data: Dict[str, Any], indent: int = 2) -> str:
    """Format JSON data for pretty printing"""
    return json.dumps(data, indent=indent, ensure_ascii=False)


def print_success(message: str):
    """Print success message"""
    print(f"✅ {message}")


def print_error(message: str):
    """Print error message"""
    print(f"❌ {message}")


def print_info(message: str):
    """Print info message"""
    print(f"ℹ️  {message}")


def load_env_config() -> str:
    """Get API URL from environment variable or use default"""
    # Check environment variable first
    url = os.environ.get('GEISTER_API_URL', '')
    if url:
        return url.rstrip('/')
    
    # Default to production API
    return "https://geister-api.realmsgos.dev "


def cmd_ask(args, client: AshokaClient):
    """Handle ask command"""
    verbose = getattr(args, 'verbose', False)
    
    # Determine question source
    question = args.question
    if args.question_file:
        try:
            with open(args.question_file, 'r', encoding='utf-8') as f:
                question = f.read().strip()
            if verbose:
                print_info(f"Loaded question from {args.question_file}")
        except Exception as e:
            print_error(f"Failed to load question file: {e}")
            traceback.print_exc()
            return
    
    # Validate that we have a question from either source
    if not question:
        print_error("No question provided. Use either 'question' argument or --question-file")
        return
    
    if verbose:
        print_info(f"Asking question: '{question[:100]}{'...' if len(question) > 100 else ''}'")
    
    # Load realm status from file if provided
    realm_status = None
    if args.realm_status_file:
        try:
            with open(args.realm_status_file, 'r') as f:
                realm_status = json.load(f)
            if verbose:
                print_info(f"Loaded realm status from {args.realm_status_file}")
        except Exception as e:
            print_error(f"Failed to load realm status file: {e}")
            traceback.print_exc()
            return
    
    result = client.ask_question(
        question=question,
        user_principal=args.user_principal,
        realm_principal=args.realm_principal,
        persona=args.persona,
        ollama_url=args.ollama_url,
        realm_status=realm_status,
        stream=args.stream
    )
    
    if result.get("success"):
        if verbose:
            print_success("Question answered successfully")
        print(f"{result['answer']}")
    else:
        print_error(f"Failed to get answer: {result.get('error', 'Unknown error')}")


def cmd_suggestions(args, client: AshokaClient):
    """Handle suggestions command"""
    print_info("Getting contextual suggestions...")
    
    result = client.get_suggestions(
        user_principal=args.user_principal,
        realm_principal=args.realm_principal,
        persona=args.persona,
        ollama_url=args.ollama_url
    )
    
    if result.get("suggestions"):
        print_success("Suggestions generated")
        print(f"\n💡 Suggestions from {result.get('persona_used', 'Ashoka').title()}:")
        for i, suggestion in enumerate(result["suggestions"], 1):
            print(f"   {i}. {suggestion}")
        print()
    else:
        print_error("Failed to get suggestions")


def cmd_personas(args, client: AshokaClient):
    """Handle personas command"""
    if args.action == "list":
        result = client.list_personas()
        if result.get("success"):
            print_success(f"Found {len(result['personas'])} personas")
            print(f"\n👥 Available Personas (default: {result['default_persona']}):")
            for persona in result["personas"]:
                marker = " ⭐" if persona["name"] == result["default_persona"] else ""
                print(f"   • {persona['name']}{marker}")
                if persona.get("description"):
                    print(f"     {persona['description']}")
            print()
        else:
            print_error("Failed to list personas")
    
    elif args.action == "show":
        if not args.name:
            print_error("Persona name required for 'show' action")
            return
        
        result = client.get_persona(args.name)
        if result.get("success"):
            print_success(f"Persona '{args.name}' details")
            print(f"\n📝 Persona: {result['name']}")
            print(f"Default: {'Yes' if result['is_default'] else 'No'}")
            if args.verbose:
                print(f"\nContent:\n{result['content']}")
                if result.get('validation'):
                    val = result['validation']
                    print(f"\nValidation:")
                    print(f"  Characters: {val.get('character_count', 0)}")
                    print(f"  Words: {val.get('word_count', 0)}")
                    print(f"  Lines: {val.get('line_count', 0)}")
            print()
        else:
            print_error(f"Persona '{args.name}' not found")
    
    elif args.action == "create":
        if not args.name or not args.content:
            print_error("Both --name and --content required for 'create' action")
            return
        
        # Read content from file if it's a path
        content = args.content
        if Path(args.content).exists():
            try:
                with open(args.content, 'r') as f:
                    content = f.read()
                print_info(f"Loaded content from {args.content}")
            except Exception as e:
                print_error(f"Failed to read content file: {e}")
                traceback.print_exc()
                return
        
        result = client.create_persona(args.name, content)
        if result.get("success"):
            print_success(f"Created persona '{args.name}'")
        else:
            print_error(f"Failed to create persona: {result.get('error', 'Unknown error')}")
    
    elif args.action == "delete":
        if not args.name:
            print_error("Persona name required for 'delete' action")
            return
        
        result = client.delete_persona(args.name)
        if result.get("success"):
            print_success(f"Deleted persona '{args.name}'")
        else:
            print_error(f"Failed to delete persona: {result.get('error', 'Unknown error')}")


def cmd_realm(args, client: AshokaClient):
    """Handle realm command"""
    if args.action == "status":
        if not args.principal:
            print_error("Realm principal required for 'status' action")
            return
        
        result = client.get_realm_status(args.principal)
        if result.get("success"):
            data = result["data"]
            print_success(f"Realm status for {args.principal}")
            print(f"\n🏛️  Realm: {data.get('status_data', {}).get('realm_name', 'Unknown')}")
            print(f"Principal: {data.get('realm_principal', 'Unknown')}")
            print(f"Health Score: {data.get('health_score', 0)}/100")
            print(f"Last Updated: {data.get('last_updated', 'Unknown')}")
            
            status_data = data.get('status_data', {})
            # Handle nested structure: status_data.data.status contains the actual metrics
            metrics = status_data.get('data', {}).get('status', status_data)
            print(f"\n📊 Metrics:")
            print(f"   Users: {metrics.get('users_count', 0)}")
            print(f"   Organizations: {metrics.get('organizations_count', 0)}")
            print(f"   Proposals: {metrics.get('proposals_count', 0)}")
            print(f"   Votes: {metrics.get('votes_count', 0)}")
            print(f"   Extensions: {len(metrics.get('extensions', []))}")
            
            if args.verbose:
                print(f"\n🔍 Raw Data:")
                print(format_json_output(data))
            print()
        else:
            print_error(f"Realm status not found for {args.principal}")
    
    elif args.action == "fetch":
        if not args.principal:
            print_error("Realm principal required for 'fetch' action")
            return
        
        print_info(f"Fetching realm status for {args.principal}...")
        result = client.fetch_realm_status(args.principal, args.url or "", args.network)
        if result.get("success"):
            print_success(f"Successfully fetched and stored realm status")
        else:
            print_error(f"Failed to fetch realm status: {result.get('error', 'Unknown error')}")
    
    elif args.action == "list":
        result = client.get_all_realms_status()
        if result.get("success"):
            realms = result["data"]
            print_success(f"Found {len(realms)} tracked realms")
            print(f"\n🏛️  Tracked Realms:")
            for realm in realms:
                status_data = realm.get('status_data', {})
                metrics = status_data.get('data', {}).get('status', status_data)
                name = metrics.get('realm_name', status_data.get('realm_name', 'Unknown'))
                principal = realm.get('realm_principal', 'Unknown')[:12] + "..."
                health = realm.get('health_score', 0)
                users = metrics.get('users_count', 0)
                print(f"   • {name} ({principal}) - Health: {health}/100, Users: {users}")
            print()
        else:
            print_error("Failed to list realms")


def cmd_health(args, client: AshokaClient):
    """Handle health command"""
    print_info(f"Checking API health at {client.base_url}...")
    result = client.health_check()
    
    if result.get("status") == "ok":
        print_success("API is healthy")
        timeout = result.get("inactivity_timeout_seconds", 0)
        if timeout > 0:
            since_activity = result.get("seconds_since_last_activity", 0)
            print(f"   Inactivity timeout: {timeout}s ({timeout/3600:.1f}h)")
            print(f"   Time since last activity: {since_activity}s")
        else:
            print("   Inactivity timeout: disabled")
    else:
        print_error("API health check failed")


def main():
    """Main CLI entry point"""
    # Load default API URL from config
    default_api_url = load_env_config()
    
    parser = argparse.ArgumentParser(
        description="Ashoka CLI - Command line interface for Ashoka AI governance assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Ask a question directly
  ashoka ask "What is a realm?" --realm-principal rdmx6-jaaaa-aaaah-qcaiq-cai

  # Ask a question from a file
  ashoka ask --question-file my_question.txt --realm-principal rdmx6-jaaaa-aaaah-qcaiq-cai

  # Get suggestions
  ashoka suggestions --realm-principal rdmx6-jaaaa-aaaah-qcaiq-cai --persona advisor

  # List personas
  ashoka personas list

  # Show persona details
  ashoka personas show ashoka --verbose

  # Create new persona
  ashoka personas create --name "expert" --content "You are a governance expert..."

  # Get realm status
  ashoka realm status --principal rdmx6-jaaaa-aaaah-qcaiq-cai

  # Fetch fresh realm data
  ashoka realm fetch --principal rdmx6-jaaaa-aaaah-qcaiq-cai

  # Check API health
  ashoka health
        """
    )
    
    parser.add_argument("--api-url", default=default_api_url, 
                       help=f"Ashoka API base URL (default: {default_api_url})")
    parser.add_argument("--verbose", "-v", action="store_true", 
                       help="Enable verbose output")
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Ask command
    ask_parser = subparsers.add_parser("ask", help="Ask a question to Ashoka")
    ask_parser.add_argument("question", nargs="?", help="Question to ask (or use --question-file)")
    ask_parser.add_argument("--question-file", help="File containing the question to ask")
    ask_parser.add_argument("--user-principal", default="", help="User principal ID")
    ask_parser.add_argument("--realm-principal", default="", help="Realm principal ID")
    ask_parser.add_argument("--persona", default="", help="Persona to use (default: ashoka)")
    ask_parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama API URL")
    ask_parser.add_argument("--realm-status-file", help="JSON file containing realm status data")
    ask_parser.add_argument("--stream", action="store_true", help="Enable streaming response")
    
    # Suggestions command
    suggestions_parser = subparsers.add_parser("suggestions", help="Get contextual suggestions")
    suggestions_parser.add_argument("--user-principal", default="", help="User principal ID")
    suggestions_parser.add_argument("--realm-principal", default="", help="Realm principal ID")
    suggestions_parser.add_argument("--persona", default="", help="Persona to use")
    suggestions_parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama API URL")
    
    # Personas command
    personas_parser = subparsers.add_parser("personas", help="Manage personas")
    personas_parser.add_argument("action", choices=["list", "show", "create", "delete"], 
                                help="Action to perform")
    personas_parser.add_argument("--name", help="Persona name")
    personas_parser.add_argument("--content", help="Persona content (text or file path)")
    
    # Realm command
    realm_parser = subparsers.add_parser("realm", help="Manage realm data")
    realm_parser.add_argument("action", choices=["status", "fetch", "list"], 
                             help="Action to perform")
    realm_parser.add_argument("--principal", help="Realm principal ID")
    realm_parser.add_argument("--url", help="Realm URL (for fetch)")
    realm_parser.add_argument("--network", default="ic", help="Network (ic/local)")
    
    # Health command
    health_parser = subparsers.add_parser("health", help="Check API health")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Initialize client
    client = AshokaClient(args.api_url)
    
    # Route to appropriate command handler
    if args.command == "ask":
        cmd_ask(args, client)
    elif args.command == "suggestions":
        cmd_suggestions(args, client)
    elif args.command == "personas":
        cmd_personas(args, client)
    elif args.command == "realm":
        cmd_realm(args, client)
    elif args.command == "health":
        cmd_health(args, client)
    else:
        print_error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
