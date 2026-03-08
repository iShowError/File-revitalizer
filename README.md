# File Revitalizer v0.2.1

> Deductive BTRFS data-recovery engine — web UI + local agent + grounded AI assistant.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      User's Browser                             │
│  Dashboard / Candidate Table / Recovery Result / AI Chat UI     │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTPS
┌────────────────────────▼────────────────────────────────────────┐
│                  Django 5 Web Server                            │
│                                                                 │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  Recovery    │  │  Artifact        │  │  Grounded        │  │
│  │  Case API    │  │  Pipeline        │  │  Chatbot         │  │
│  │  (Phase 2)   │  │  (Phase 4)       │  │  (Phase 7)       │  │
│  └──────┬───────┘  └────────┬─────────┘  └────────┬─────────┘  │
│         │                   │                      │            │
│  ┌──────▼───────────────────▼──────────────────────▼─────────┐  │
│  │                   SQLite / db.sqlite3                      │  │
│  │  RecoveryCase · Artifact · CandidateFile                   │  │
│  │  ChatSession · ChatMessage · AuditEvent                    │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │               Reconstruction Engine (Phase 5)              │  │
│  │  superblock.py · chunk_tree.py · fs_tree.py                │  │
│  │  → logical_to_physical() → confidence scoring              │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────────────┘
                          │ REST API  (over localhost or SSH tunnel)
┌─────────────────────────▼───────────────────────────────────────┐
│                  Local Agent (agent/cli.py)                     │
│  Runs on the machine with the damaged BTRFS device              │
│                                                                 │
│  health  — check btrfs tools + server reachability             │
│  scan    — dump-super · btrfs-find-root · dump-tree chunk/fs   │
│  upload  — POST each artifact to /api/cases/<id>/artifacts/    │
│  execute — run whitelisted dd/btrfs-restore commands           │
└─────────────────────────────────────────────────────────────────┘
                          │
               ┌──────────▼──────────┐
               │   BTRFS Device      │
               │   /dev/sdb (raw)    │
               └─────────────────────┘
```

---

## Release History

### v0.1.0 — Core Sprint (8 phases)

| # | Branch | What it delivers |
|---|--------|------------------|
| 1 | `feat/core-models` | RecoveryCase FSM, Artifact, CandidateFile, ChatSession, ChatMessage, AuditEvent |
| 2 | `feat/recovery-api` | REST CRUD + state-machine transition endpoints |
| 3 | `feat/local-agent` | `agent/cli.py` — health / scan / upload / execute |
| 4 | `feat/artifact-pipeline` | Parsers for superblock, chunk_tree, fs_tree |
| 5 | `feat/candidate-table` | Reconstruction engine + sortable UI table |
| 6 | `feat/one-file-recovery` | `dd` / `btrfs restore` command generator + result page |
| 7 | `feat/chatbot-grounded` | Grounded AI chat — live case context injected into system prompt |
| 8 | `feat/safety-and-tests` | Command whitelist guard + 39-test integration suite |

### v0.2.0 — Agent Packaging

- PyInstaller spec for single-binary Linux agent
- GitHub Actions workflow — builds on `v*` tags, publishes to Releases with SHA256 checksum

### v0.2.1 — Security Hardening

- `execute.py` — removed `shell=True`, shell metacharacter rejection, removed `rm`/`truncate` from whitelist
- `scan.py` — device path validation, `btrfs-find-root` stderr handling
- Dead reference cleanup (stale `.pyc` removal)

---

## Quick-Start (Server)

```bash
git clone https://github.com/iShowError/File-revitalizer.git
cd File-revitalizer/file_revitalizer

# Install dependencies
pip install django python-dotenv requests

# Configure AI provider
cat > .env << 'EOF'
AI_PROVIDER_API_KEY=sk-or-v1-...
AI_PROVIDER_API_URL=https://openrouter.ai/api/v1/chat/completions
AI_PROVIDER_MODEL=google/gemma-3-12b-it:free
EOF

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```


---

## Local Agent Setup

The agent runs on the **machine that has the damaged BTRFS device** attached.

```bash
cd agent/
pip install -r requirements.txt

# Copy and edit config
cp .env.example .env
# Set SERVER_URL, API_TOKEN, DEVICE_PATH
```

### Agent Commands

```bash
# Verify connectivity and btrfs tool versions
python cli.py health

# Scan device and upload all artifacts to an existing case
python cli.py scan --case-id 1 --device /dev/sdb

# Upload a single artifact file
python cli.py upload --case-id 1 --type superblock --file /tmp/super.txt

# Execute a recovery command (whitelisted: dd, btrfs, btrfs-find-root, btrfs-restore)
python cli.py execute --case-id 1 --command "dd if=/dev/sdb bs=512 skip=8192 count=2 > /tmp/recovered.dat"
```

See [agent/README.md](agent/README.md) for full configuration reference.

---

## Recovery Workflow

1. **Create a case** — POST `/api/cases/` with `device_path`
2. **Scan** — run `python cli.py scan --case-id <N> --device /dev/sdbX` on the damaged machine
3. **Generate candidates** — POST `/api/cases/<N>/generate-candidates/`
4. **Browse candidates** — GET `/cases/<N>/candidates/` (sortable table, confidence bars)
5. **Recover a file** — POST `/api/cases/<N>/recover/<candidate_id>/` → get dd/btrfs-restore commands
6. **Execute on the damaged machine** — `python cli.py execute --case-id <N> --command "..."`
7. **Ask the AI** — GET `/cases/<N>/chat/` — grounded assistant with full case context

---

## API Reference

| Method | URL | Description |
|--------|-----|-------------|
| GET/POST | `/api/cases/` | List or create cases |
| GET | `/api/cases/<id>/` | Case detail + counts |
| POST | `/api/cases/<id>/transition/` | Advance state machine |
| POST | `/api/cases/<id>/artifacts/` | Upload raw btrfs output |
| GET | `/api/cases/<id>/candidates/` | List candidate files |
| POST | `/api/cases/<id>/recover/<cid>/` | Generate recovery commands |
| GET | `/api/cases/<id>/audit/` | Chronological audit trail |
| POST | `/api/cases/<id>/generate-candidates/` | Run reconstruction engine |
| POST | `/api/cases/<id>/chat/` | AI chat (grounded) |

---

## Running Tests

```bash
cd file_revitalizer
python manage.py test recovery --verbosity=2
# Found 39 test(s). ... OK
```

Coverage: state machine, artifact parsers, command generator whitelist guard, all REST API endpoints, chat AI integration (mocked).

---

## Security Notes

- **Command whitelist** — `command_generator.py` validates every generated command against  
  `ALLOWED_COMMANDS = {'dd', 'btrfs', 'btrfs-find-root', 'btrfs-restore'}` before returning.  
  The same whitelist is enforced again in `agent/commands/execute.py` at execution time.
- **AuditEvent** — append-only; admin `has_change_permission` returns `False`.
- All views use `@login_required` + object-level ownership checks (`user=request.user`).
- `.env` file contains secrets — never commit it.
