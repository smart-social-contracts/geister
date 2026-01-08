# Realms Agent Cheatsheet

Reference guide for AI agents simulating **Citizens** or **Developers/Admins** of a Realm.

---

## Table of Contents
- [Entity Types](#entity-types)
- [Citizen Agent](#citizen-agent)
- [Developer/Admin Agent](#developeradmin-agent)
- [Extension APIs](#extension-apis)
- [CLI Commands](#cli-commands)
- [dfx Canister Calls](#dfx-canister-calls)
- [Internet Computer Wallet (icw)](#internet-computer-wallet-icw)

---

## Entity Types

Core GGG entities in a Realm:

| Entity | Description |
|--------|-------------|
| `User` | Citizen of the realm (identified by principal) |
| `UserProfile` | Role profile (admin, member) |
| `Realm` | The realm itself (name, description, settings) |
| `Treasury` | Realm's treasury linked to vault |
| `Proposal` | Governance proposal for voting |
| `Vote` | A user's vote on a proposal |
| `Codex` | Stored code that can be executed |
| `Task` | Scheduled/running task |
| `TaskStep` | Individual step in a task |
| `TaskSchedule` | Schedule configuration for tasks |
| `Transfer` | Token transfer record |
| `Balance` | User's balance in the vault |
| `Invoice` | Payment invoice with subaccount |
| `Organization` | Organization within the realm |
| `Mandate` | Authorization/permission grant |
| `Identity` | User identity verification |

---

## Citizen Agent

### Join a Realm
```bash
# Join as member
dfx canister call realm_backend join_realm '("member")'

# Join as admin (if permitted)
dfx canister call realm_backend join_realm '("admin")'
```

### Check Your Status
```bash
# Get your principal
dfx canister call realm_backend get_my_principal

# Get your user status (profiles, etc.)
dfx canister call realm_backend get_my_user_status

# Update profile picture
dfx canister call realm_backend update_my_profile_picture '("https://example.com/avatar.png")'
```

### Query Entities
```bash
# List entities with pagination (class_name, page_num, page_size, order)
dfx canister call realm_backend get_objects_paginated '("User", 0, 10, "desc")'
dfx canister call realm_backend get_objects_paginated '("Proposal", 0, 10, "desc")'
dfx canister call realm_backend get_objects_paginated '("Transfer", 0, 20, "desc")'

# Get specific objects by type and ID
dfx canister call realm_backend get_objects '(vec { 
  record { 0 = "User"; 1 = "1" }; 
  record { 0 = "Realm"; 1 = "1" }; 
})'
```

### Voting (via extension)
```bash
# Get all proposals
realms realm call extension voting get_proposals '{}' -f <realm_folder>

# Get proposals by status
realms realm call extension voting get_proposals '{"status": "pending_review"}' -f <realm_folder>

# Get specific proposal
realms realm call extension voting get_proposal '{"proposal_id": "prop_001"}' -f <realm_folder>

# Cast a vote (yes/no/abstain)
realms realm call extension voting cast_vote '{
  "proposal_id": "prop_001",
  "vote": "yes",
  "voter": "<your_user_id>"
}' -f <realm_folder>

# Check your vote on a proposal
realms realm call extension voting get_user_vote '{
  "proposal_id": "prop_001",
  "voter": "<your_user_id>"
}' -f <realm_folder>

# Submit a new proposal
realms realm call extension voting submit_proposal '{
  "title": "Increase Treasury Allocation",
  "description": "Proposal to increase monthly UBI by 10%",
  "code_url": "https://example.com/proposal_code.py",
  "proposer": "<your_user_id>"
}' -f <realm_folder>
```

### Vault / Treasury (via extension)
```bash
# Get your balance
realms realm call extension vault get_balance '{"principal_id": "<your_principal>"}' -f <realm_folder>

# Get vault status
realms realm call extension vault get_status '{}' -f <realm_folder>

# Get your transactions
realms realm call extension vault get_transactions '{"principal_id": "<your_principal>"}' -f <realm_folder>

# Refresh transactions from ledger
realms realm call extension vault refresh '{"force": true}' -f <realm_folder>

# Refresh specific invoice
realms realm call extension vault refresh_invoice '{"invoice_id": "inv_001"}' -f <realm_folder>
```

---

## Developer/Admin Agent

### Realm Management

```bash
# Create a new realm
realms realm create --realm-name "My Realm" --network local

# Create and deploy immediately
realms realm create --realm-name "My Realm" --deploy --network local

# Create with random demo data
realms realm create --realm-name "Test Realm" --random --members 50 --organizations 5

# Deploy existing realm folder
realms realm deploy --folder .realms/realm_MyRealm_20250108 --network local

# Deploy with reinstall (wipes state)
realms realm deploy --folder <path> --network local --mode reinstall
```

### Import Data
```bash
# Import codex files
realms import my_codex.py --type codex
realms import manifest --type Codex

# Import task objects
realms import my_task_objects.json

# Import realm data
realms import realm_data.json
```

### Process/Task Management
```bash
# List all tasks
realms ps ls

# View task logs
realms ps logs <task_id>

# Start a task
realms ps start <task_id>

# Stop/kill a task
realms ps kill <task_id>

# Run script and wait for completion
realms run --file my_script.py --wait --wait-timeout 5
```

### Execute Code Dynamically
```bash
# Execute sync code
dfx canister call realm_backend execute_code '("from ggg import User; print([u.id for u in User.instances()])")'

# Execute code (returns task_id for async)
dfx canister call realm_backend execute_code '("
from ggg import Proposal
proposals = list(Proposal.instances())
for p in proposals:
    print(f\"{p.proposal_id}: {p.title} - {p.status}\")
")'

# Execute shell-style code
dfx canister call realm_backend execute_code_shell '("2 + 2")'
```

### Task Scheduling
```bash
# Create scheduled task (via dfx)
dfx canister call realm_backend create_scheduled_task '(
  "my_task",
  "from ggg import User; print(len(list(User.instances())))",
  0,
  3600000000000
)'

# Stop a task
dfx canister call realm_backend stop_task '("task_id")'

# Start a task
dfx canister call realm_backend start_task '("task_id")'

# Get task logs
dfx canister call realm_backend get_task_logs '("task_id")'
dfx canister call realm_backend get_task_logs_by_name '("task_name")'
```

### Realm Configuration
```bash
# Update realm config
dfx canister call realm_backend update_realm_config '("{
  \"name\": \"Updated Realm Name\",
  \"description\": \"New description\",
  \"logo\": \"logo.png\",
  \"welcome_message\": \"Welcome to our realm!\"
}")'

# Register with realm registry
dfx canister call realm_backend register_realm_with_registry '("<registry_principal>")'

# Get registry info
dfx canister call realm_backend get_realm_registry_info

# Reload entity method overrides
dfx canister call realm_backend reload_entity_method_overrides
```

### Proposal Management (Admin)
```bash
# Approve a proposal (moves to accepted status)
realms realm call extension voting approve_proposal '{"proposal_id": "prop_001"}' -f <realm_folder>

# Execute approved proposal (creates/updates codex)
realms realm call extension voting execute_proposal '{"proposal_id": "prop_001"}' --async -f <realm_folder>

# Fetch proposal code for review
realms realm call extension voting fetch_proposal_code '{"proposal_id": "prop_001"}' --async -f <realm_folder>
```

### Vault Administration
```bash
# Set canister principal
realms realm call extension vault set_canister '{
  "canister_name": "ckBTC ledger",
  "principal_id": "<ledger_principal>"
}' -f <realm_folder>

# Transfer tokens (admin only)
realms realm call extension vault transfer '{
  "to_principal": "<recipient>",
  "amount": 100000000,
  "token": "ckBTC"
}' --async -f <realm_folder>
```

### Deployment Scripts
```bash
# Deploy local dev (build)
scripts/deploy_local_dev.sh -s .realms/realm_* -b

# Deploy local dev (frontend only)
scripts/deploy_local_dev.sh -s .realms/realm_* -f

# Deploy mundus realms
scripts/deploy_local_dev.sh -s .realms/mundus/mundus_*/realm_Agora_*/ -b
```

---

## Extension APIs

### Available Extensions
| Extension | Description |
|-----------|-------------|
| `voting` | Governance voting system |
| `vault` | Treasury and token management |
| `member_dashboard` | Member profile and activity |
| `admin_dashboard` | Admin controls |
| `public_dashboard` | Public realm info |
| `market_place` | Trading/marketplace |
| `justice_litigation` | Dispute resolution |
| `land_registry` | Land/property registry |
| `llm_chat` | LLM integration |
| `passport_verification` | Identity verification |
| `notifications` | Notification system |
| `metrics` | Analytics and metrics |
| `task_monitor` | Task monitoring |
| `zone_selector` | Geographic zone selection |

### Extension Call Pattern
```bash
# Sync call
realms realm call extension <ext_name> <function> '<json_args>' -f <realm_folder>

# Async call (for operations that make inter-canister calls)
realms realm call extension <ext_name> <function> '<json_args>' --async -f <realm_folder>

# Direct dfx call
dfx canister call realm_backend extension_sync_call '(record { 
  extension_name = "<ext_name>"; 
  function_name = "<function>"; 
  args = "<json_args>"; 
})'
```

### Voting Extension Functions
| Function | Args | Description |
|----------|------|-------------|
| `get_proposals` | `{"status": "..."}` | List proposals (optional filter) |
| `get_proposal` | `{"proposal_id": "..."}` | Get single proposal |
| `submit_proposal` | `{"title", "description", "code_url", "proposer"}` | Create proposal |
| `cast_vote` | `{"proposal_id", "vote", "voter"}` | Vote yes/no/abstain |
| `get_user_vote` | `{"proposal_id", "voter"}` | Check user's vote |
| `approve_proposal` | `{"proposal_id"}` | Admin: approve proposal |
| `execute_proposal` | `{"proposal_id"}` | Admin: execute approved proposal |
| `fetch_proposal_code` | `{"proposal_id"}` | Fetch code from URL |

### Vault Extension Functions
| Function | Args | Description |
|----------|------|-------------|
| `get_balance` | `{"principal_id": "..."}` | Get user balance |
| `get_status` | `{}` | Get vault stats |
| `get_transactions` | `{"principal_id": "..."}` | Get transaction history |
| `transfer` | `{"to_principal", "amount", "token?"}` | Transfer tokens |
| `refresh` | `{"force?", "subaccount?", "token?"}` | Sync from ledger |
| `refresh_invoice` | `{"invoice_id": "..."}` | Check invoice payment |
| `set_canister` | `{"canister_name", "principal_id"}` | Configure canister |

---

## CLI Commands

### Full CLI Reference
```bash
# Realm commands
realms realm create [options]      # Create new realm
realms realm deploy [options]      # Deploy realm
realms realm call <method> <args>  # Call backend method

# Import commands
realms import <file> [--type <type>]

# Process commands
realms ps ls                       # List tasks
realms ps logs <id>               # View logs
realms ps start <id>              # Start task
realms ps kill <id>               # Stop task

# Run commands
realms run --file <file> [--wait] [--wait-timeout <seconds>]

# Mundus commands (multi-realm)
realms mundus create [options]
realms mundus deploy [options]
realms mundus status [options]
```

---

## dfx Canister Calls

### Backend Entrypoints
```bash
# Status & Info
dfx canister call realm_backend status
dfx canister call realm_backend get_extensions
dfx canister call realm_backend get_my_principal
dfx canister call realm_backend get_canister_id
dfx canister call realm_backend get_zones '(6)'  # H3 resolution

# User Management
dfx canister call realm_backend join_realm '("member")'
dfx canister call realm_backend get_my_user_status
dfx canister call realm_backend update_my_profile_picture '("<url>")'

# Entity Queries
dfx canister call realm_backend get_objects_paginated '("<class>", <page>, <size>, "<order>")'
dfx canister call realm_backend get_objects '(vec { record { 0 = "<class>"; 1 = "<id>" }; })'

# Extension Calls
dfx canister call realm_backend extension_sync_call '(record { extension_name = "..."; function_name = "..."; args = "..."; })'
dfx canister call realm_backend extension_async_call '(record { extension_name = "..."; function_name = "..."; args = "..."; })'

# Code Execution
dfx canister call realm_backend execute_code '("<python_code>")'
dfx canister call realm_backend execute_code_shell '("<code>")'
dfx canister call realm_backend download_file '("<url>", "<codex_name>", null, null)'

# Task Management
dfx canister call realm_backend stop_task '("<task_id>")'
dfx canister call realm_backend start_task '("<task_id>")'
dfx canister call realm_backend get_task_logs '("<task_id>")'
dfx canister call realm_backend get_task_logs_by_name '("<task_name>")'
dfx canister call realm_backend create_scheduled_task '("<name>", "<code>", <run_at>, <repeat_every>)'

# Registry
dfx canister call realm_backend register_realm_with_registry '("<registry_principal>")'
dfx canister call realm_backend get_realm_registry_info
dfx canister call realm_backend update_realm_config '("<config_json>")'
```

---

## Internet Computer Wallet (icw)

```bash
# Check balance
icw -n <network> -t realms balance --ledger <ledger_principal>

# Transfer tokens
icw -n <network> -t realms transfer <recipient> 500.0 --ledger <ledger_principal> --fee 0

# Direct dfx transfer
dfx canister call <ledger> icrc1_transfer '(record { 
  to = record { owner = principal "<recipient>"; subaccount = null }; 
  amount = 1000_00000000; 
  fee = null; 
  memo = null; 
  created_at_time = null; 
  from_subaccount = null 
})' --network <network>
```

---

## Hooks (for Custom Logic)

Important hooks that can be overridden via Codex:

| Hook | Entity | Description |
|------|--------|-------------|
| `Treasury.send_hook` | Treasury | Called when sending from treasury |
| `User.user_register_posthook` | User | Called after user registration |

Override pattern in manifest:
```json
{
  "entity_method_overrides": [
    {
      "entity": "Treasury",
      "method": "send_hook",
      "implementation": "Codex.my_hooks.custom_send_hook",
      "type": "method"
    }
  ]
}
```

---

## Quick Reference

### Proposal Status Flow
```
pending_review → accepted → executed
                    ↓
                 rejected
```

### Vote Choices
- `yes` - Approve
- `no` - Reject  
- `abstain` - Abstain

### User Profiles
- `admin` - Full administrative access
- `member` - Standard citizen access

### Token Amounts
- ckBTC: 1 ckBTC = 100,000,000 satoshis (8 decimals)
- REALM: Check specific token decimals

---

*Generated for Geister AI agents interacting with Realms*
