"""scan command — run BTRFS inspection commands and upload as artifacts.

Runs on the user's Linux machine. Executes:
  1. btrfs inspect-internal dump-super <device>          → superblock artifact
  2. btrfs inspect-internal dump-super -a <device>       → all superblocks
  3. btrfs-find-root <device>                            → find-root artifact
  4. btrfs inspect-internal dump-tree -t chunk <device>  → chunk_tree artifact
  5. btrfs inspect-internal dump-tree -t fs <device>     → fs_tree artifact
  6. btrfs inspect-internal dump-tree -t extent <device> → extent_tree artifact
     (steps 3–6 skipped when --superblock-only)

Each result is uploaded to /api/cases/<id>/artifacts/ on the web server.
"""
import json
import subprocess
import sys
import tempfile
import os

try:
    import requests
except ImportError:
    sys.exit('requests is not installed. Run: pip install -r requirements.txt')

from .upload import upload_raw


def _run_cmd(cmd: list, timeout: int = 120) -> tuple[bool, str, str]:
    """Run a shell command. Returns (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except FileNotFoundError:
        return False, '', f'Command not found: {cmd[0]}'
    except subprocess.TimeoutExpired:
        return False, '', f'Command timed out after {timeout}s: {" ".join(cmd)}'
    except Exception as e:
        return False, '', str(e)


def run(server: str, token: str, device: str, case_id: int,
        superblock_only: bool = False) -> bool:
    """Execute scan and upload all artifacts. Returns True if at least one
    artifact was uploaded successfully."""

    print(f'\n[scan] Device: {device}  |  Case ID: {case_id}')
    print(f'[scan] Server: {server}')
    print('[scan] Starting BTRFS inspection ...\n')

    uploaded = 0
    errors = []

    # ── 1. Primary superblock ────────────────────────────────────────────────
    cmd = ['btrfs', 'inspect-internal', 'dump-super', device]
    print(f'  Running: {" ".join(cmd)}')
    ok, out, err = _run_cmd(cmd, timeout=30)
    if ok and out:
        success = upload_raw(
            server=server, token=token, case_id=case_id,
            raw_data=out, artifact_type='superblock',
            source_command=' '.join(cmd),
        )
        if success:
            uploaded += 1
            print('  [✓] Superblock artifact uploaded.')
        else:
            errors.append('Failed to upload superblock artifact.')
    else:
        errors.append(f'dump-super failed: {err}')
        print(f'  [✗] dump-super error: {err}')

    if superblock_only:
        print('\n[scan] --superblock-only flag set. Stopping here.')
        return uploaded > 0

    # ── 2. btrfs-find-root ───────────────────────────────────────────────────
    cmd = ['btrfs-find-root', device]
    print(f'\n  Running: {" ".join(cmd)}')
    ok, out, err = _run_cmd(cmd, timeout=60)
    if ok and out:
        success = upload_raw(
            server=server, token=token, case_id=case_id,
            raw_data=out, artifact_type='find_root',
            source_command=' '.join(cmd),
        )
        if success:
            uploaded += 1
            print('  [✓] find-root artifact uploaded.')
        else:
            errors.append('Failed to upload find-root artifact.')
    else:
        # Non-fatal — btrfs-find-root may not be available everywhere
        print(f'  [–] btrfs-find-root skipped: {err or "no output"}')

    # ── 3. Chunk tree ────────────────────────────────────────────────────────
    cmd = ['btrfs', 'inspect-internal', 'dump-tree', '-t', 'chunk', device]
    print(f'\n  Running: {" ".join(cmd)}')
    ok, out, err = _run_cmd(cmd, timeout=300)
    if ok and out:
        success = upload_raw(
            server=server, token=token, case_id=case_id,
            raw_data=out, artifact_type='chunk_tree',
            source_command=' '.join(cmd),
        )
        if success:
            uploaded += 1
            print('  [✓] Chunk tree artifact uploaded.')
        else:
            errors.append('Failed to upload chunk tree artifact.')
    else:
        print(f'  [–] chunk tree skipped: {err or "no output"}')

    # ── 4. FS tree (root subvolume) ──────────────────────────────────────────
    cmd = ['btrfs', 'inspect-internal', 'dump-tree', '-t', 'fs', device]
    print(f'\n  Running: {" ".join(cmd)}')
    ok, out, err = _run_cmd(cmd, timeout=600)
    if ok and out:
        success = upload_raw(
            server=server, token=token, case_id=case_id,
            raw_data=out, artifact_type='fs_tree',
            source_command=' '.join(cmd),
        )
        if success:
            uploaded += 1
            print('  [✓] FS tree artifact uploaded.')
        else:
            errors.append('Failed to upload FS tree artifact.')
    else:
        print(f'  [–] FS tree skipped: {err or "no output"}')

    # ── 5. Extent tree ───────────────────────────────────────────────────────
    # Provides logical→extent mappings with inode back-references.
    # Enables more precise physical address resolution than the chunk map alone.
    cmd = ['btrfs', 'inspect-internal', 'dump-tree', '-t', 'extent', device]
    print(f'\n  Running: {" ".join(cmd)}')
    ok, out, err = _run_cmd(cmd, timeout=600)
    if ok and out:
        success = upload_raw(
            server=server, token=token, case_id=case_id,
            raw_data=out, artifact_type='extent_tree',
            source_command=' '.join(cmd),
        )
        if success:
            uploaded += 1
            print('  [✓] Extent tree artifact uploaded.')
        else:
            errors.append('Failed to upload extent tree artifact.')
    else:
        print(f'  [–] extent tree skipped: {err or "no output"}')

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f'\n[scan] Uploaded {uploaded} artifact(s).')
    if errors:
        print('[scan] Errors:')
        for e in errors:
            print(f'  ✗ {e}')

    return uploaded > 0
