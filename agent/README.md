# File Revitalizer — Local Recovery Agent

The agent is a lightweight Python CLI that runs **on your Linux machine** (where the damaged BTRFS device is physically connected). It talks to the File Revitalizer web server to deliver BTRFS metadata artifacts and receive recovery instructions.

---

## Requirements

- Python 3.9+
- BTRFS tools: `btrfs-progs` (`btrfs`, `btrfs-find-root`)
- Network access to the File Revitalizer web server

Install Python dependencies:

```bash
pip install -r agent/requirements.txt
```

Install BTRFS tools (Debian/Ubuntu):

```bash
sudo apt install btrfs-progs
```

---

## Configuration

Either pass `--server` and `--token` on every command, or create `agent/.env`:

```ini
AGENT_SERVER_URL=http://192.168.1.10:8000
AGENT_API_TOKEN=your-api-token-here
```

---

## Quick Start

### 1. Health check

Verify the agent can reach the server and that BTRFS tools are installed:

```bash
python agent/cli.py health --server http://192.168.1.10:8000 --token <token>
```

### 2. Scan device

Run all BTRFS inspection commands and upload artifacts to an existing case:

```bash
python agent/cli.py scan --device /dev/sdb --case-id 3
```

Use `--superblock-only` for a quick first pass:

```bash
python agent/cli.py scan --device /dev/sdb --case-id 3 --superblock-only
```

### 3. Upload a file manually

If you already have command output saved to a file:

```bash
python agent/cli.py upload \
    --file /tmp/dump-super.txt \
    --type superblock \
    --case-id 3 \
    --command "btrfs inspect-internal dump-super /dev/sdb"
```

---

## Commands

| Command | Description |
|---------|-------------|
| `health` | Ping server + check local tool availability |
| `scan` | Run BTRFS commands and upload all artifacts |
| `upload` | Upload a single file as an artifact |

---

## Artifact Types

| Type | Source command |
|------|----------------|
| `superblock` | `btrfs inspect-internal dump-super <dev>` |
| `chunk_tree` | `btrfs inspect-internal dump-tree -t chunk <dev>` |
| `fs_tree` | `btrfs inspect-internal dump-tree -t fs <dev>` |
| `extent_tree` | `btrfs inspect-internal dump-tree -t extent <dev>` |
| `find_root` | `btrfs-find-root <dev>` |
| `other` | Any other output |

---

## Architecture

```
[Your Linux machine]              [File Revitalizer server]
  agent/cli.py
    └── commands/health.py  ──→  GET  /api/cases/
    └── commands/scan.py    ──→  POST /api/cases/<id>/artifacts/
    └── commands/upload.py  ──→  POST /api/cases/<id>/artifacts/
```

Artifacts are parsed server-side (Phase 4) and used to reconstruct deleted
file candidates (Phase 5) without the agent needing any parsing logic.
