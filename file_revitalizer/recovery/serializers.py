"""Plain-dict serializers for the recovery API.

No external DRF dependency — each function converts a model instance to a
JSON-serialisable dict. Import these in views.py to keep that file clean.
"""

def serialize_case(case):
    """RecoveryCase → dict."""
    return {
        'id': case.pk,
        'title': case.title,
        'device_path': case.device_path,
        'filesystem_uuid': case.filesystem_uuid,
        'state': case.state,
        'notes': case.notes,
        'allowed_transitions': case.TRANSITIONS.get(case.state, []),
        'created_at': case.created_at.isoformat(),
        'updated_at': case.updated_at.isoformat(),
    }


def serialize_artifact(artifact):
    """Artifact → dict (raw_data omitted to keep payloads small)."""
    return {
        'id': artifact.pk,
        'case_id': artifact.case_id,
        'artifact_type': artifact.artifact_type,
        'source_command': artifact.source_command,
        'parsed_data': artifact.parsed_data,
        'uploaded_at': artifact.uploaded_at.isoformat(),
        'parsed_at': artifact.parsed_at.isoformat() if artifact.parsed_at else None,
    }


def serialize_candidate(candidate):
    """CandidateFile → dict."""
    return {
        'id': candidate.pk,
        'case_id': candidate.case_id,
        'inode_number': candidate.inode_number,
        'reconstructed_path': candidate.reconstructed_path,
        'file_name': candidate.file_name,
        'file_size': candidate.file_size,
        'file_type': candidate.file_type,
        'logical_address': candidate.logical_address,
        'physical_address': candidate.physical_address,
        'extent_count': candidate.extent_count,
        'extent_map': candidate.extent_map,
        'confidence': round(candidate.confidence, 4),
        'status': candidate.status,
        'discovered_at': candidate.discovered_at.isoformat(),
        'recovered_at': candidate.recovered_at.isoformat() if candidate.recovered_at else None,
    }


def serialize_audit_event(event):
    """AuditEvent → dict."""
    return {
        'id': event.pk,
        'case_id': event.case_id,
        'user': event.user.username if event.user else None,
        'event_type': event.event_type,
        'summary': event.summary,
        'detail': event.detail,
        'created_at': event.created_at.isoformat(),
    }
