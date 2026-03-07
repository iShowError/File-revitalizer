# File Revitalizer — Local Recovery Agent

The agent is a lightweight CLI tool that runs **on your Linux machine** (where the damaged BTRFS device is physically connected). It talks to the File Revitalizer web server to deliver BTRFS metadata artifacts and receive recovery instructions.

---

## Installation

### Option A: Download pre-built binary (recommended)

Download the latest binary from [GitHub Releases](https://github.com/iShowError/File-revitalizer/releases/latest):

```bash
# Download the latest release
wget https://github.com/iShowError/File-revitalizer/releases/latest/download/file-revitalizer-agent

# Make it executable
chmod +x file-revitalizer-agent

# Verify it works
./file-revitalizer-agent --version
```

> **Note:** The binary is a self-contained Linux x86_64 executable — no Python installation required.

### Option B: Run from source

If you prefer running from source (requires Python 3.9+):

```bash
git clone https://github.com/iShowError/File-revitalizer.git
cd File-revitalizer
pip install -r agent/requirements.txt
python agent/cli.py --version
```

### Option C: Build your own binary

```bash
pip install pyinstaller -r agent/requirements.txt
pyinstaller agent/file-revitalizer-agent.spec
./dist/file-revitalizer-agent --version
```

---

## System Requirements

- **OS:** Linux (x86_64)
- **BTRFS tools:** `btrfs-progs` (`btrfs`, `btrfs-find-root`)
- **Network:** Access to the File Revitalizer web server
- **Permissions:** `sudo` or root access for raw disk operations

Install BTRFS tools (Debian/Ubuntu):

```bash
sudo apt install btrfs-progs
```

---

## Configuration

Either pass `--server` and `--token` on every command, or create a `.env` file next to the binary:

```ini
AGENT_SERVER_URL=http://192.168.1.10:8000
AGENT_API_TOKEN=your-api-token-here
```

---

## Quick Start

### 1. List available devices

```bash
./file-revitalizer-agent list-devices
```

### 2. Health check

Verify the agent can reach the server and that BTRFS tools are installed:

```bash
./file-revitalizer-agent health --server http://192.168.1.10:8000 --token <token>
```

### 3. Scan device

Run all BTRFS inspection commands and upload artifacts to an existing case:

```bash
sudo ./file-revitalizer-agent scan --device /dev/sdb --case-id 3
```

Use `--superblock-only` for a quick first pass:

```bash
sudo ./file-revitalizer-agent scan --device /dev/sdb --case-id 3 --superblock-only
```

### 4. Upload a single artifact manually

If you already have command output saved to a file:

```bash
./file-revitalizer-agent upload \
    --file /tmp/dump-super.txt \
    --type superblock \
    --case-id 3 \
    --command "btrfs inspect-internal dump-super /dev/sdb"
```

### 5. Execute recovery commands

Run server-provided recovery commands for a candidate file:

```bash
sudo ./file-revitalizer-agent execute \
    --commands '["dd if=/dev/sdb of=/tmp/recovered.bin bs=4096 skip=12345 count=100"]' \
    --candidate-id 7 \
    --case-id 3
```

---

## Commands

| Command | Description |
|---------|-------------|
| `list-devices` | List block devices on this machine (uses `lsblk`) |
| `health` | Ping server + check local BTRFS tool availability |
| `scan` | Run BTRFS commands and upload all artifacts |
| `upload` | Upload a single file as an artifact |
| `execute` | Run server-provided recovery commands (whitelisted) |

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

## Security

- Commands executed via `execute` are **whitelisted** — only `dd`, `btrfs`, `btrfs-find-root`, `btrfs-restore`, `mkdir`, `cat`, `rm`, and `truncate` are allowed.
- API tokens are never logged.
- All uploads go over HTTPS in production.
- The agent never writes to the damaged device — all operations are read-only.

---

## Verifying Downloads

Each release includes a `.sha256` checksum file:

```bash
wget https://github.com/iShowError/File-revitalizer/releases/latest/download/file-revitalizer-agent.sha256
sha256sum -c file-revitalizer-agent.sha256
```

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
