"""execute command — run a whitelisted recovery command on behalf of the server.

The server sends a command string via:
    POST /api/agent/execute
    Body: { "commands": ["dd if=...", "..."], "candidate_id": 42 }

This module:
1. Validates each command against the whitelist (ALLOWED_COMMANDS).
2. Rejects shell metacharacters (no pipes, chains, redirections).
3. Executes each command sequentially (without shell=True).
4. Returns stdout/stderr for each command.
5. Refuses to run anything not in the whitelist.
6. Verifies output file exists and reports size/hash to the server.
"""
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

try:
    import requests
except ImportError:
    sys.exit('requests is not installed. Run: pip install -r requirements.txt')

# Only genuinely safe, read-oriented recovery tools.
# dd is write-capable but essential for block-level extraction (of= targets
# are validated separately).  No destructive tools (rm, truncate, etc.).
ALLOWED_COMMANDS = frozenset([
    'dd', 'btrfs', 'btrfs-find-root', 'btrfs-restore', 'mkdir', 'cat',
])

# Shell metacharacters that indicate command chaining / redirection.
# We reject the entire command if any of these appear outside of quotes.
_SHELL_META = re.compile(r'[;|&`$><\n]')


def _is_allowed(command_str: str) -> tuple[bool, str]:
    """Validate a command string. Returns (allowed, reason)."""
    # Reject shell metacharacters first (before any parsing)
    if _SHELL_META.search(command_str):
        return False, 'contains shell metacharacters (;|&`$><)'

    try:
        tokens = shlex.split(command_str)
    except ValueError as e:
        return False, f'cannot parse command: {e}'

    if not tokens:
        return False, 'empty command'

    binary = os.path.basename(tokens[0])
    if binary not in ALLOWED_COMMANDS:
        return False, f'"{binary}" not in whitelist: {sorted(ALLOWED_COMMANDS)}'

    return True, ''


def _run_single(cmd_str: str, timeout: int = 300) -> dict:
    """Execute one command (without shell). Returns result dict."""
    allowed, reason = _is_allowed(cmd_str)
    if not allowed:
        return {
            'command': cmd_str,
            'returncode': -1,
            'stdout': '',
            'stderr': f'BLOCKED: {reason}',
            'blocked': True,
        }

    try:
        tokens = shlex.split(cmd_str)
        result = subprocess.run(
            tokens,
            shell=False,
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
    except FileNotFoundError:
        return {
            'command': cmd_str,
            'returncode': -1,
            'stdout': '',
            'stderr': f'Command not found: {tokens[0]}',
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

    # Post-execution verification
    if all_ok and server and token and case_id and candidate_id:
        _verify_output(server, token, case_id, candidate_id, commands)

    return all_ok


def _find_output_path(commands: list) -> str | None:
    """Extract the output file path from dd of= or btrfs-restore target."""
    for cmd in reversed(commands):
        # dd of=/path/to/file
        match = re.search(r'\bof=(\S+)', cmd)
        if match:
            return match.group(1)
        # btrfs restore ... /target/dir  (last arg is the target)
        tokens = shlex.split(cmd)
        if tokens and os.path.basename(tokens[0]) == 'btrfs-restore' and len(tokens) >= 3:
            return tokens[-1]
    return None


def _sha256_file(path: str, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _verify_output(server: str, token: str, case_id: int,
                   candidate_id: int, commands: list):
    """Check if the output file exists and report verification to the server."""
    output_path = _find_output_path(commands)
    if not output_path:
        print('[verify] Could not determine output file path from commands.')
        return

    file_exists = os.path.isfile(output_path)
    file_size = os.path.getsize(output_path) if file_exists else 0
    file_hash = ''
    if file_exists and file_size < 1_073_741_824:  # hash files < 1 GB
        try:
            file_hash = _sha256_file(output_path)
        except OSError:
            pass

    print(f'[verify] Output: {output_path}  exists={file_exists}  '
          f'size={file_size}  sha256={file_hash[:16]}...')

    url = f'{server.rstrip("/")}/api/cases/{case_id}/verify/{candidate_id}/'
    payload = {
        'file_exists': file_exists,
        'file_size': file_size,
        'sha256': file_hash,
    }
    try:
        resp = requests.post(
            url, json=payload,
            headers={'Authorization': f'Token {token}'},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f'[verify] Server: {data.get("status", "?")} '
                  f'(size_match={data.get("size_match", "?")})')
        else:
            print(f'[verify] Server returned HTTP {resp.status_code}')
    except requests.exceptions.RequestException as e:
        print(f'[verify] Could not report verification: {e}')
