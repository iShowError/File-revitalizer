#!/usr/bin/env python3
"""File Revitalizer — Local Recovery Agent CLI.

This script runs on the user's local Linux machine (where the damaged BTRFS
device is connected). It communicates with the Django web server to upload
artifacts and receive recovery instructions.

Usage examples:
    python cli.py list-devices
    python cli.py health  --server http://192.168.1.10:8000 --token <api_token>
    python cli.py scan    --device /dev/sdb --case-id 3 --server ... --token ...
    python cli.py upload  --file superblock.json --type superblock --case-id 3 \
                          --server ... --token ...
"""
import argparse
import sys
import os

# Resolve the real directory of this script (works under PyInstaller --onefile too)
if getattr(sys, 'frozen', False):
    _AGENT_DIR = os.path.dirname(sys.executable)
else:
    _AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
    # Allow running as `python agent/cli.py` from the repo root
    sys.path.insert(0, _AGENT_DIR)

from dotenv import load_dotenv

# Load .env from the agent directory if present (TOKEN, SERVER_URL)
load_dotenv(os.path.join(_AGENT_DIR, '.env'))


def _add_common_args(parser):
    """Add --server and --token to any subcommand parser."""
    parser.add_argument(
        '--server',
        default=os.getenv('AGENT_SERVER_URL', 'http://127.0.0.1:8000'),
        help='Base URL of the File Revitalizer web server (default: $AGENT_SERVER_URL)',
    )
    parser.add_argument(
        '--token',
        default=os.getenv('AGENT_API_TOKEN', ''),
        help='API token for authenticating with the web server (default: $AGENT_API_TOKEN)',
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog='file-revitalizer-agent',
        description='Local recovery agent for File Revitalizer',
    )
    parser.add_argument('--version', action='version', version='%(prog)s 0.2.1')
    subparsers = parser.add_subparsers(dest='subcommand', required=True)

    # ── list-devices ─────────────────────────────────────────────────────────
    subparsers.add_parser(
        'list-devices',
        help='List block devices on this machine (uses lsblk)',
    )

    # ── health ─────────────────────────────────────────────────────────────
    health_p = subparsers.add_parser(
        'health',
        help='Check connectivity to server and report local tool availability',
    )
    _add_common_args(health_p)

    # ── scan ────────────────────────────────────────────────────────────────
    scan_p = subparsers.add_parser(
        'scan',
        help='Run BTRFS inspection commands and upload results as artifacts',
    )
    _add_common_args(scan_p)
    scan_p.add_argument('--device', required=True,
                        help='Block device to scan (e.g. /dev/sdb)')
    scan_p.add_argument('--case-id', required=True, type=int,
                        help='RecoveryCase ID on the web server')
    scan_p.add_argument('--superblock-only', action='store_true',
                        help='Only dump the superblock (faster, less data)')

    # ── upload ──────────────────────────────────────────────────────────────
    upload_p = subparsers.add_parser(
        'upload',
        help='Upload a local file as an artifact to the web server',
    )
    _add_common_args(upload_p)
    upload_p.add_argument('--file', required=True,
                          help='Path to the file to upload')
    upload_p.add_argument('--type', required=True,
                          choices=['superblock', 'chunk_tree', 'fs_tree',
                                   'extent_tree', 'find_root', 'other'],
                          dest='artifact_type',
                          help='Artifact type')
    upload_p.add_argument('--case-id', required=True, type=int,
                          help='RecoveryCase ID on the web server')
    upload_p.add_argument('--command', default='',
                          help='Command that produced this file (for audit log)')

    # ── execute ─────────────────────────────────────────────────────────────
    exec_p = subparsers.add_parser(
        'execute',
        help='Run server-provided recovery commands (whitelisted)',
    )
    _add_common_args(exec_p)
    exec_p.add_argument('--commands', required=True,
                        help='JSON array of shell commands to execute')
    exec_p.add_argument('--candidate-id', type=int, default=None,
                        help='CandidateFile ID (for result reporting)')
    exec_p.add_argument('--case-id', type=int, default=None,
                        help='RecoveryCase ID (for result reporting)')

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.subcommand == 'list-devices':
        from commands.list_devices import run as run_list_devices
        success = run_list_devices()
        sys.exit(0 if success else 1)

    elif args.subcommand == 'health':
        from commands.health import run as run_health
        success = run_health(args.server, args.token)
        sys.exit(0 if success else 1)

    elif args.subcommand == 'scan':
        from commands.scan import run as run_scan
        success = run_scan(
            server=args.server,
            token=args.token,
            device=args.device,
            case_id=args.case_id,
            superblock_only=args.superblock_only,
        )
        sys.exit(0 if success else 1)

    elif args.subcommand == 'upload':
        from commands.upload import run as run_upload
        success = run_upload(
            server=args.server,
            token=args.token,
            file_path=args.file,
            artifact_type=args.artifact_type,
            case_id=args.case_id,
            source_command=args.command,
        )
        sys.exit(0 if success else 1)

    elif args.subcommand == 'execute':
        import json as _json
        from commands.execute import run as run_execute
        try:
            commands = _json.loads(args.commands)
        except Exception:
            print('[execute] --commands must be a valid JSON array of strings.')
            sys.exit(1)
        success = run_execute(
            server=args.server,
            token=args.token,
            commands=commands,
            candidate_id=args.candidate_id,
            case_id=args.case_id,
        )
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
