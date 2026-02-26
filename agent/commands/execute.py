"""execute command — run a whitelisted recovery command on behalf of the server.

The server sends a command string via:
    POST /api/agent/execute
    Body: { "commands": ["dd if=...", "..."], "candidate_id": 42 }

This module:
1. Validates each command against the whitelist (ALLOWED_COMMANDS).
2. Executes each command sequentially.
3. Returns stdout/stderr for each command.
4. Refuses to run anything not in the whitelist.
"""
import json
import shlex
import subprocess
import sys
import os

try:
    import requests
except ImportError:
    sys.exit('requests is not installed. Run: pip install -r requirements.txt')

# Mirror of server-side whitelist in command_generator.py
ALLOWED_COMMANDS = frozenset(['dd', 'btrfs', 'btrfs-find-root', 'btrfs-restore',
                               'mkdir', 'cat', 'rm', 'truncate'])


def _is_allowed(command_str: str) -> bool:
    """Return True if the first token of the command is in ALLOWED_COMMANDS."""
    try:
        tokens = shlex.split(command_str)
    except ValueError:
        return False
    if not tokens:
        return False
    binary = os.path.basename(tokens[0])
    return binary in ALLOWED_COMMANDS


def _run_single(cmd_str: str, timeout: int = 300) -> dict:
    """Execute one shell command. Returns {command, returncode, stdout, stderr}."""
    if not _is_allowed(cmd_str):
        return {
            'command': cmd_str,
            'returncode': -1,
            'stdout': '',
            'stderr': f'BLOCKED: command not in whitelist. Allowed: {sorted(ALLOWED_COMMANDS)}',
            'blocked': True,
        }

    try:
        result = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            'command': cmd_str,
            'returncode': result.returncode,
            'stdout': result.stdout[-4096:] if result.stdout else '',  # cap at 4KB
            'stderr': result.stderr[-2048:] if result.stderr else '',
            'blocked': False,
        }
    except subprocess.TimeoutExpired:
        return {
            'command': cmd_str,
            'returncode': -1,
            'stdout': '',
            'stderr': f'Command timed out after {timeout}s.',
            'blocked': False,
        }
    except Exception as e:
        return {
            'command': cmd_str,
            'returncode': -1,
            'stdout': '',
            'stderr': str(e),
            'blocked': False,
        }


def run(server: str, token: str, commands: list, candidate_id: int = None,
        case_id: int = None) -> bool:
    """Execute a list of commands and POST results back to the server.

    Returns True if all commands succeeded.
    """
    print(f'\n[execute] Running {len(commands)} command(s) for candidate #{candidate_id}')
    results = []
    all_ok = True

    for cmd in commands:
        print(f'  $ {cmd}')
        r = _run_single(cmd)
        results.append(r)
        if r['returncode'] != 0 or r.get('blocked'):
            all_ok = False
            print(f'  [✗] rc={r["returncode"]} {r["stderr"][:120]}')
        else:
            print(f'  [✓] rc=0')

    # Report results back to server
    if server and token and case_id and candidate_id:
        url = f'{server.rstrip("/")}/api/cases/{case_id}/recovery-result/'
        payload = {
            'candidate_id': candidate_id,
            'results': results,
            'all_ok': all_ok,
        }
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={'Authorization': f'Token {token}'},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                print('[execute] Results reported to server. ✓')
            else:
                print(f'[execute] Server returned {resp.status_code} when reporting results.')
        except requests.exceptions.RequestException as e:
            print(f'[execute] Could not report results to server: {e}')

    return all_ok
