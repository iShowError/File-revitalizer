"""health command — ping the web server and report local BTRFS tool availability."""
import platform
import shutil
import sys

try:
    import requests
except ImportError:
    sys.exit('requests is not installed. Run: pip install -r requirements.txt')


# BTRFS tools we check for
REQUIRED_TOOLS = ['btrfs', 'btrfs-find-root']
OPTIONAL_TOOLS = ['btrfscue', 'testdisk', 'foremost', 'dd', 'xxd']


def _check_tools():
    """Return dicts of {tool: path_or_None} for required and optional tools."""
    required = {t: shutil.which(t) for t in REQUIRED_TOOLS}
    optional = {t: shutil.which(t) for t in OPTIONAL_TOOLS}
    return required, optional


def run(server: str, token: str) -> bool:
    """Execute health check. Returns True on success."""
    print(f'\n[health] Checking connectivity to {server} ...')

    # 1. Ping dedicated health endpoint
    try:
        resp = requests.get(
            f'{server.rstrip("/")}/api/agent/health/',
            headers={'Authorization': f'Token {token}'},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'ok':
                print(f'  [✓] Server reachable — version {data.get("server_version", "?")}, '
                      f'authenticated as {data.get("user", "?")}')
                server_ok = True
            else:
                print(f'  [✗] Server returned unexpected payload: {data}')
                server_ok = False
        elif resp.status_code == 401:
            print(f'  [✗] Server reachable but token is invalid/inactive (HTTP 401)')
            server_ok = False
        else:
            print(f'  [✗] Server returned unexpected status {resp.status_code}')
            server_ok = False
    except requests.exceptions.ConnectionError:
        print(f'  [✗] Cannot connect to {server}')
        server_ok = False
    except requests.exceptions.Timeout:
        print(f'  [✗] Connection timed out')
        server_ok = False

    # 2. Check local tools
    required, optional = _check_tools()
    print('\n[health] Required BTRFS tools:')
    all_required_ok = True
    for tool, path in required.items():
        if path:
            print(f'  [✓] {tool}: {path}')
        else:
            print(f'  [✗] {tool}: NOT FOUND')
            all_required_ok = False

    print('\n[health] Optional tools:')
    for tool, path in optional.items():
        mark = '✓' if path else '–'
        loc = path or 'not found'
        print(f'  [{mark}] {tool}: {loc}')

    # 3. OS info
    print(f'\n[health] System: {platform.system()} {platform.release()} '
          f'({platform.machine()})')
    print(f'[health] Python: {platform.python_version()}')

    # 4. Summary
    overall = server_ok and all_required_ok
    status = 'PASS' if overall else 'FAIL'
    print(f'\n[health] Result: {status}')
    if not all_required_ok:
        print('  ⚠ Install missing required tools before running `scan`.')
        print('    On Debian/Ubuntu: sudo apt install btrfs-progs')
    return overall
