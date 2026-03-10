"""Recovery report generation.

Produces a structured summary of a completed (or in-progress) RecoveryCase
including timeline, artifacts, candidate outcomes, and chat highlights.
"""
from django.utils import timezone

from .models import RecoveryCase, AuditEvent


def generate_report(case: RecoveryCase) -> dict:
    """Build a JSON-serialisable report dict for *case*."""
    return {
        'case': _case_section(case),
        'timeline': _timeline_section(case),
        'artifacts': _artifacts_section(case),
        'candidates': _candidates_section(case),
        'chat_summary': _chat_section(case),
        'generated_at': timezone.now().isoformat(),
    }


# -- private helpers --------------------------------------------------------

def _case_section(case):
    return {
        'id': case.pk,
        'title': case.title,
        'device_path': case.device_path,
        'filesystem_uuid': case.filesystem_uuid or '',
        'state': case.state,
        'created_at': case.created_at.isoformat(),
        'updated_at': case.updated_at.isoformat(),
        'notes': case.notes,
    }


def _timeline_section(case):
    events = case.audit_events.order_by('created_at').values(
        'event_type', 'summary', 'created_at',
    )
    return [
        {
            'event_type': e['event_type'],
            'summary': e['summary'],
            'timestamp': e['created_at'].isoformat(),
        }
        for e in events
    ]


def _artifacts_section(case):
    arts = case.artifacts.order_by('uploaded_at')
    return {
        'count': arts.count(),
        'items': [
            {
                'type': a.artifact_type,
                'source_command': a.source_command,
                'uploaded_at': a.uploaded_at.isoformat(),
                'parsed': bool(a.parsed_data),
            }
            for a in arts
        ],
    }


def _candidates_section(case):
    candidates = case.candidates.all()
    total = candidates.count()
    by_status = {}
    for c in candidates:
        by_status.setdefault(c.status, 0)
        by_status[c.status] += 1

    items = [
        {
            'id': c.pk,
            'file_name': c.file_name,
            'file_size': c.file_size,
            'confidence': c.confidence,
            'status': c.status,
            'recovered_at': c.recovered_at.isoformat() if c.recovered_at else None,
        }
        for c in candidates
    ]

    return {
        'total': total,
        'by_status': by_status,
        'items': items,
    }


def _chat_section(case):
    """Return the last few assistant messages as a brief summary."""
    sessions = case.chat_sessions.all()
    highlights = []
    for session in sessions:
        msgs = session.messages.filter(role='assistant').order_by('-created_at')[:3]
        for m in msgs:
            highlights.append({
                'content': m.content[:500],
                'timestamp': m.created_at.isoformat(),
            })
    return highlights[:10]
