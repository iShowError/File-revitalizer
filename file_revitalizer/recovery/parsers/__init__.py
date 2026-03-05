"""Artifact parsers package.

Each parser module exposes a single function:
    parse(raw_data: str) -> dict

The package-level parse_artifact() function is the single entry point
used by the artifact_upload view (views.py) to auto-invoke the correct parser.
"""
from django.utils import timezone

from .superblock import parse as parse_superblock
from .chunk_tree import parse as parse_chunk_tree
from .fs_tree import parse as parse_fs_tree
from .extent_tree import parse as parse_extent_tree
from .find_root import parse as parse_find_root


# Map artifact_type string → parser function
_PARSERS = {
    'superblock':   parse_superblock,
    'chunk_tree':   parse_chunk_tree,
    'fs_tree':      parse_fs_tree,
    'extent_tree':  parse_extent_tree,
    'find_root':    parse_find_root,
}


def parse_artifact(artifact) -> bool:
    """Parse an Artifact instance in-place.

    Sets artifact.parsed_data and artifact.parsed_at, then saves.
    Returns True if a specialised parser ran, False if skipped.
    """
    parser = _PARSERS.get(artifact.artifact_type)
    if parser is None:
        return False

    try:
        result = parser(artifact.raw_data)
        artifact.parsed_data = result
        artifact.parsed_at = timezone.now()
        artifact.save(update_fields=['parsed_data', 'parsed_at'])
        return True
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            'Parser error for artifact %s (%s): %s',
            artifact.pk, artifact.artifact_type, exc,
        )
        return False
