"""Context builder for the grounded chatbot — Phase 7.

Extracts live case state and injects it into every AI prompt so the chatbot
answers are grounded in the actual recovery situation, not generic knowledge.

Context injected into every system prompt:
    - Case ID, state, device, FS UUID
    - Artifact inventory (types uploaded + parsed status)
    - Candidate summary (count, highest confidence, file types)
    - Last 3 audit events (most recent activity)
    - Superblock metadata if available (generation, total_bytes, fsid)

The caller (chat_message view) is responsible for sending this context
as the system message and the user's question as the human message.
"""
from .models import RecoveryCase, Artifact, CandidateFile, AuditEvent


def build_context(case: RecoveryCase) -> dict:
    """Return a structured context dict for the given case."""
    ctx: dict = {
        'case_id': case.pk,
        'case_title': case.title,
        'state': case.state,
        'device_path': case.device_path,
        'filesystem_uuid': case.filesystem_uuid or 'unknown',
    }

    # ── Artifacts ─────────────────────────────────────────────────────────
    artifacts = list(case.artifacts.order_by('-uploaded_at')[:20])
    ctx['artifacts'] = [
        {
            'type': a.artifact_type,
            'parsed': bool(a.parsed_data),
            'uploaded_at': a.uploaded_at.isoformat(),
        }
        for a in artifacts
    ]

    # Pull superblock metadata if parsed
    sb = next((a for a in artifacts
               if a.artifact_type == Artifact.TYPE_SUPERBLOCK and a.parsed_data), None)
    if sb:
        pd = sb.parsed_data
        ctx['superblock'] = {
            'fsid': pd.get('fsid'),
            'generation': pd.get('generation'),
            'total_bytes_human': pd.get('total_bytes_human'),
            'bytes_used_human': pd.get('bytes_used_human'),
            'label': pd.get('label'),
            'nodesize': pd.get('nodesize'),
        }

    # ── Candidates ────────────────────────────────────────────────────────
    candidates_qs = case.candidates.order_by('-confidence')
    total_candidates = candidates_qs.count()
    top_candidate = candidates_qs.first()
    high_conf = candidates_qs.filter(confidence__gte=0.65).count()
    ctx['candidates'] = {
        'total': total_candidates,
        'high_confidence': high_conf,
        'highest_confidence': round(top_candidate.confidence, 3) if top_candidate else None,
        'top_file': top_candidate.file_name if top_candidate else None,
    }

    # ── Recent audit events ───────────────────────────────────────────────
    recent_events = list(
        case.audit_events.order_by('-created_at')[:3]
    )
    ctx['recent_events'] = [
        {
            'type': e.event_type,
            'summary': e.summary,
            'at': e.created_at.isoformat(),
        }
        for e in recent_events
    ]

    return ctx


def build_system_prompt(case: RecoveryCase) -> str:
    """Build the full system prompt string to prepend to every chat request."""
    ctx = build_context(case)

    artifacts_summary = ', '.join(
        f"{a['type']}({'parsed' if a['parsed'] else 'raw'})"
        for a in ctx['artifacts']
    ) or 'none uploaded yet'

    sb = ctx.get('superblock', {})
    sb_summary = (
        f"FS UUID={sb.get('fsid','?')}, "
        f"generation={sb.get('generation','?')}, "
        f"total={sb.get('total_bytes_human','?')}, "
        f"used={sb.get('bytes_used_human','?')}"
    ) if sb else 'not yet parsed'

    cands = ctx['candidates']
    cand_summary = (
        f"{cands['total']} total, {cands['high_confidence']} high-confidence"
        f"{f', top file: {cands[\"top_file\"]}' if cands['top_file'] else ''}"
    ) if cands['total'] else 'none generated yet'

    recent = '\n'.join(
        f"  - [{e['type']}] {e['summary']}" for e in ctx['recent_events']
    ) or '  (none)'

    return f"""You are File Revitalizer's expert BTRFS data recovery assistant.
You help users recover deleted files from a damaged BTRFS filesystem.
Always base your answers on the current case context below.
Be concise, technical, and step-by-step when giving recovery instructions.

=== CURRENT RECOVERY CASE CONTEXT ===
Case ID      : {ctx['case_id']} — {ctx['case_title']}
State        : {ctx['state']}
Device       : {ctx['device_path']}
Filesystem   : {ctx['filesystem_uuid']}
Artifacts    : {artifacts_summary}
Superblock   : {sb_summary}
Candidates   : {cand_summary}
Recent events:
{recent}
======================================

Answer the user's question below. If they ask about a step not yet completed
(e.g. asking about candidates before artifacts are uploaded), guide them to
complete the prerequisite steps first."""
