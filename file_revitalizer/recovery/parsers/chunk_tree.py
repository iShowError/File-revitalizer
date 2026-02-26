"""Chunk tree parser for `btrfs inspect-internal dump-tree -t chunk` output.

Builds a logical→physical offset map used to translate logical byte addresses
(from the FS/extent trees) into physical LBAs for `dd` recovery commands.

Each CHUNK_ITEM line in the dump looks like:
        item X key (FIRST_CHUNK_TREE CHUNK_ITEM <logical_offset>) ...
            length <len> owner ...
            stripe 0 devid 1 offset <physical_offset>

We extract tuples of (logical_offset, physical_offset, length) and store them
as a sorted list so callers can do a binary search.
"""
import re


# Match the key line for a chunk item
_KEY_RE = re.compile(
    r'key\s+\(\s*\d+\s+CHUNK_ITEM\s+(\d+)\s*\)',
    re.IGNORECASE,
)
# Match the length line immediately after
_LEN_RE = re.compile(r'length\s+(\d+)', re.IGNORECASE)
# Match the stripe offset line
_STRIPE_RE = re.compile(
    r'stripe\s+\d+\s+devid\s+(\d+)\s+offset\s+(\d+)',
    re.IGNORECASE,
)


def parse(raw_data: str) -> dict:
    """Parse dump-tree chunk output. Returns chunk map sorted by logical."""
    chunks = []
    lines = raw_data.splitlines()
    i = 0
    while i < len(lines):
        key_match = _KEY_RE.search(lines[i])
        if key_match:
            logical = int(key_match.group(1))
            length = None
            physical = None
            devid = None
            # Scan next few lines for length and stripe info
            for j in range(i + 1, min(i + 20, len(lines))):
                if length is None:
                    lm = _LEN_RE.search(lines[j])
                    if lm:
                        length = int(lm.group(1))
                if physical is None:
                    sm = _STRIPE_RE.search(lines[j])
                    if sm:
                        devid = int(sm.group(1))
                        physical = int(sm.group(2))
                if length is not None and physical is not None:
                    break

            if length is not None and physical is not None:
                chunks.append({
                    'logical': logical,
                    'physical': physical,
                    'length': length,
                    'devid': devid,
                })
        i += 1

    chunks.sort(key=lambda c: c['logical'])

    return {
        '_parser': 'chunk_tree',
        'chunk_count': len(chunks),
        'chunks': chunks,
    }


def logical_to_physical(chunk_map: list, logical_addr: int) -> int | None:
    """Translate a logical address to a physical one using the parsed chunk map.

    chunk_map is the 'chunks' list from parse().
    Returns None if no matching chunk is found.
    """
    # Binary search for the last chunk whose logical <= logical_addr
    lo, hi = 0, len(chunk_map) - 1
    result = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if chunk_map[mid]['logical'] <= logical_addr:
            result = mid
            lo = mid + 1
        else:
            hi = mid - 1

    if result is None:
        return None

    chunk = chunk_map[result]
    offset_within_chunk = logical_addr - chunk['logical']
    if offset_within_chunk >= chunk['length']:
        return None  # Address is beyond the end of this chunk

    return chunk['physical'] + offset_within_chunk
