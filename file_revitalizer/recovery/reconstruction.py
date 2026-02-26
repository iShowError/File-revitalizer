"""Deleted file reconstruction engine — Phase 5.

Takes the parsed artifacts attached to a RecoveryCase and produces a
list of CandidateFile rows.

Algorithm:
1. Load the fs_tree artifact (INODE_ITEM + EXTENT_DATA records + path table).
2. Load the chunk_tree artifact (logical→physical map).
3. All inodes with size > 0 and at least one EXTENT_DATA reference are candidates.
4. For each candidate inode:
   a. Collect all EXTENT_DATA → translate logical→physical via chunk map.
   b. Score confidence (see CONFIDENCE_* constants).
   c. Detect likely file type from filename extension or size.
5. Upsert CandidateFile rows (update if already exists for this case+inode).

Confidence scoring:
    single_extent (count == 1)                      → 0.70
    multi-extent but all contiguous                  → 0.55
    fragmented (non-contiguous extents)              → 0.35
    nlink == 0 (orphaned inode — definitely deleted) → +0.15 bonus
    size > 0 verified from INODE_ITEM               → +0.05 bonus
    extent_count == 0 (inline data, best-effort)    → 0.20
"""
import mimetypes
import os
from typing import Optional

from .models import Artifact, CandidateFile
from .parsers.chunk_tree import logical_to_physical


# ── Confidence constants ─────────────────────────────────────────────────────
CONF_SINGLE_EXTENT = 0.70
CONF_MULTI_CONTIGUOUS = 0.55
CONF_FRAGMENTED = 0.35
CONF_INLINE = 0.20

BONUS_ORPHANED = 0.15   # nlink == 0
BONUS_SIZE_KNOWN = 0.05  # size > 0 from INODE_ITEM


def _are_contiguous(extents: list) -> bool:
    """Return True if all extents are physically contiguous (no gaps)."""
    if len(extents) <= 1:
        return True
    sorted_e = sorted(extents, key=lambda e: e.get('file_offset', 0))
    for i in range(1, len(sorted_e)):
        prev = sorted_e[i - 1]
        curr = sorted_e[i]
        expected_physical = prev.get('physical', 0) + prev.get('length', 0)
        if curr.get('physical', 0) != expected_physical:
            return False
    return True


def _score(extents: list, nlink: int, size: int) -> float:
    n = len(extents)
    if n == 0:
        score = CONF_INLINE
    elif n == 1:
        score = CONF_SINGLE_EXTENT
    elif _are_contiguous(extents):
        score = CONF_MULTI_CONTIGUOUS
    else:
        score = CONF_FRAGMENTED

    if nlink == 0:
        score += BONUS_ORPHANED
    if size > 0:
        score += BONUS_SIZE_KNOWN

    return min(round(score, 4), 1.0)


def _file_type_from_name(name: str) -> str:
    if not name:
        return 'unknown'
    mime, _ = mimetypes.guess_type(name)
    if mime:
        return mime.split('/')[0]
    ext = os.path.splitext(name)[1].lower()
    ext_map = {
        '.txt': 'text', '.md': 'text', '.log': 'text',
        '.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.gif': 'image',
        '.mp3': 'audio', '.wav': 'audio', '.flac': 'audio',
        '.mp4': 'video', '.avi': 'video', '.mkv': 'video',
        '.pdf': 'document', '.doc': 'document', '.docx': 'document',
        '.zip': 'archive', '.tar': 'archive', '.gz': 'archive',
        '.py': 'code', '.js': 'code', '.c': 'code', '.h': 'code',
        '.db': 'database', '.sqlite': 'database',
    }
    return ext_map.get(ext, 'unknown')


def reconstruct_candidates(case) -> dict:
    """Main entry point. Returns { 'created': N, 'updated': N, 'errors': [...] }"""
    result = {'created': 0, 'updated': 0, 'errors': []}

    # 1. Load fs_tree artifact (most recent)
    fs_artifact = (
        case.artifacts
        .filter(artifact_type=Artifact.TYPE_FS_TREE)
        .exclude(parsed_data={})
        .order_by('-uploaded_at')
        .first()
    )
    if not fs_artifact:
        result['errors'].append('No parsed fs_tree artifact found for this case.')
        return result

    # 2. Load chunk_tree artifact (optional — improves physical address resolution)
    chunk_artifact = (
        case.artifacts
        .filter(artifact_type=Artifact.TYPE_CHUNK_TREE)
        .exclude(parsed_data={})
        .order_by('-uploaded_at')
        .first()
    )
    chunk_map = []
    if chunk_artifact:
        chunk_map = chunk_artifact.parsed_data.get('chunks', [])

    fs_data = fs_artifact.parsed_data
    inodes = fs_data.get('inodes', {})
    path_table = fs_data.get('path_table', {})

    if not inodes:
        result['errors'].append('fs_tree artifact contained no inode records.')
        return result

    # 3. Process each inode
    skipped = 0
    for inode_str, inode_info in inodes.items():
        try:
            inode_num = int(inode_str)
        except (ValueError, TypeError):
            skipped += 1
            continue

        size = inode_info.get('size', 0)
        nlink = inode_info.get('nlink', 0)
        raw_extents = inode_info.get('extents', [])

        # Skip inodes that are definitely live (nlink > 0 AND size > 0)
        # We include everything to let the user filter by confidence.
        # Truly orphaned (nlink == 0) get the confidence bonus.

        # Translate logical→physical in extent map
        translated_extents = []
        for ext in raw_extents:
            log_addr = ext.get('disk_bytenr', 0)
            phys_addr = None
            if chunk_map and log_addr:
                phys_addr = logical_to_physical(chunk_map, log_addr)
            translated_extents.append({
                'logical': log_addr,
                'physical': phys_addr,
                'file_offset': ext.get('file_offset', 0),
                'length': ext.get('length', 0),
            })

        confidence = _score(translated_extents, nlink, size)

        # Primary extent for quick dd access
        primary = translated_extents[0] if translated_extents else {}
        logical_addr = primary.get('logical') or None
        physical_addr = primary.get('physical') or None

        # Reconstruct file name / path
        full_path = path_table.get(inode_num, '') or path_table.get(str(inode_num), '')
        file_name = os.path.basename(full_path) if full_path else ''
        file_type = _file_type_from_name(file_name)

        # Upsert CandidateFile
        candidate, created = CandidateFile.objects.update_or_create(
            case=case,
            inode_number=inode_num,
            defaults={
                'reconstructed_path': full_path,
                'file_name': file_name,
                'file_size': size,
                'file_type': file_type,
                'logical_address': logical_addr,
                'physical_address': physical_addr,
                'extent_count': len(translated_extents),
                'extent_map': translated_extents,
                'confidence': confidence,
            },
        )
        if created:
            result['created'] += 1
        else:
            result['updated'] += 1

    if skipped:
        result['errors'].append(f'{skipped} inode keys could not be parsed as integers.')

    return result
