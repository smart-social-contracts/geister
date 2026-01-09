#!/usr/bin/env python3
"""
Backup RunPod template configuration.

Usage:
    RUNPOD_API_KEY=xxx python scripts/backup_template.py [--template-name NAME]

Saves template configuration to templates/ directory (excluding secret values).
"""

import os
import sys
import argparse
import json
import requests
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_api_key():
    """Get RunPod API key from environment"""
    api_key = os.getenv('RUNPOD_API_KEY')
    if not api_key:
        raise ValueError("RUNPOD_API_KEY not found in environment")
    return api_key


def get_templates(api_key: str):
    """Get all pod templates for the user (filters out public RunPod templates)"""
    query = """
    query {
        myself {
            podTemplates {
                id
                name
                imageName
                dockerArgs
                containerDiskInGb
                volumeInGb
                volumeMountPath
                ports
                env {
                    key
                    value
                }
                startJupyter
                startSsh
                isServerless
                isPublic
                readme
            }
        }
    }
    """
    response = requests.post(
        'https://api.runpod.io/graphql',
        headers={'Authorization': f'Bearer {api_key}'},
        json={'query': query}
    )
    response.raise_for_status()
    data = response.json()
    
    if 'errors' in data:
        raise Exception(f"GraphQL errors: {data['errors']}")
    
    templates = data.get('data', {}).get('myself', {}).get('podTemplates', [])
    # Filter out public RunPod templates, keep only user's own templates
    return [t for t in templates if not t.get('isPublic', False)]


def sanitize_env_vars(env_list):
    """Replace secret values with placeholders"""
    if not env_list:
        return []
    
    secret_keywords = ['key', 'secret', 'token', 'password', 'pem', 'api', 'auth', 'credential', 'creds', 'private']
    sanitized = []
    
    for env in env_list:
        key = env.get('key', '')
        value = env.get('value', '')
        
        # Check if this looks like a secret
        is_secret = any(kw in key.lower() for kw in secret_keywords)
        
        sanitized.append({
            'key': key,
            'value': '<REDACTED>' if is_secret else value
        })
    
    return sanitized


def main():
    parser = argparse.ArgumentParser(
        description="Backup RunPod template configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--template-name', '-t', type=str, default='geister-template-1',
                       help='Template name to backup (default: geister-template-1)')
    parser.add_argument('--list', '-l', action='store_true',
                       help='List all available templates')
    parser.add_argument('--output', '-o', type=str, default=None,
                       help='Output file path (default: templates/<name>.json)')
    
    args = parser.parse_args()
    
    try:
        api_key = get_api_key()
    except ValueError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    
    print("🔄 Fetching templates from RunPod...")
    templates = get_templates(api_key)
    
    if args.list:
        print("\n=== Available Templates ===")
        for t in templates:
            print(f"  • {t['name']} (ID: {t['id']})")
        return
    
    # Find the requested template
    template = None
    for t in templates:
        if t['name'] == args.template_name:
            template = t
            break
    
    if not template:
        print(f"❌ Template '{args.template_name}' not found.")
        print("\nAvailable templates:")
        for t in templates:
            print(f"  • {t['name']}")
        sys.exit(1)
    
    # Sanitize secrets
    template_backup = template.copy()
    template_backup['env'] = sanitize_env_vars(template.get('env', []))
    template_backup['_backup_date'] = datetime.utcnow().isoformat() + 'Z'
    template_backup['_note'] = 'Secret values have been redacted. Set them manually when recreating.'
    
    # Determine output path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    templates_dir = os.path.join(parent_dir, 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    output_path = args.output or os.path.join(templates_dir, f"{args.template_name}.json")
    
    # Save to file
    with open(output_path, 'w') as f:
        json.dump(template_backup, f, indent=2)
    
    print(f"\n✅ Template '{args.template_name}' backed up to: {output_path}")
    print(f"\n📋 Template Summary:")
    print(f"   ID: {template['id']}")
    print(f"   Name: {template['name']}")
    print(f"   Image: {template['imageName']}")
    print(f"   Container Disk: {template['containerDiskInGb']}GB")
    print(f"   Volume: {template['volumeInGb']}GB at {template['volumeMountPath']}")
    print(f"   Ports: {template['ports']}")
    print(f"   Environment Variables: {len(template.get('env', []))} vars")
    
    redacted_count = sum(1 for e in template_backup['env'] if e['value'] == '<REDACTED>')
    if redacted_count:
        print(f"   ⚠️  {redacted_count} secret value(s) redacted")


if __name__ == '__main__':
    main()
