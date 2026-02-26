"""upload command — upload a local file (or raw string) as an artifact.

Used directly via CLI:
    python cli.py upload --file output.txt --type superblock --case-id 3

Also used internally by the scan command via upload_raw().
"""
import json
import os
import sys

try:
    import requests
except ImportError:
    sys.exit('requests is not installed. Run: pip install -r requirements.txt')


def upload_raw(server: str, token: str, case_id: int, raw_data: str,
               artifact_type: str, source_command: str = '') -> bool:
    """Upload a raw string as an artifact. Returns True on success."""
    url = f'{server.rstrip("/")}/api/cases/{case_id}/artifacts/'
    payload = {
        'artifact_type': artifact_type,
        'raw_data': raw_data,
        'source_command': source_command,
    }
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={
                'Authorization': f'Token {token}',
                'Content-Type': 'application/json',
                'X-CSRFToken': '',  # CSRF exempt on API endpoints
            },
            timeout=60,
        )
        if resp.status_code in (200, 201):
            return True
        else:
            print(f'  [upload] Server returned {resp.status_code}: {resp.text[:200]}')
            return False
    except requests.exceptions.RequestException as e:
        print(f'  [upload] Network error: {e}')
        return False


def run(server: str, token: str, file_path: str, artifact_type: str,
        case_id: int, source_command: str = '') -> bool:
    """Upload a file from disk as an artifact. Returns True on success."""
    if not os.path.isfile(file_path):
        print(f'[upload] File not found: {file_path}')
        return False

    file_size = os.path.getsize(file_path)
    print(f'\n[upload] File: {file_path} ({file_size:,} bytes)')
    print(f'[upload] Type: {artifact_type}  |  Case ID: {case_id}')

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as fh:
            raw_data = fh.read()
    except Exception as e:
        print(f'[upload] Cannot read file: {e}')
        return False

    success = upload_raw(
        server=server,
        token=token,
        case_id=case_id,
        raw_data=raw_data,
        artifact_type=artifact_type,
        source_command=source_command or f'file: {os.path.basename(file_path)}',
    )

    if success:
        print('[upload] ✓ Artifact uploaded successfully.')
    else:
        print('[upload] ✗ Upload failed.')
    return success
