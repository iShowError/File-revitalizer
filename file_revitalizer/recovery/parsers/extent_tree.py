"""Extent tree parser for `btrfs inspect-internal dump-tree -t extent` output.

Builds a logical-address → physical-extent map that is more precise than the
chunk map alone: the extent tree records the *actual* data extents plus back-
references that link each extent to the inode that owns it.

Records extracted
-----------------
EXTENT_ITEM (DATA flag only):
    key (<logical_addr> EXTENT_ITEM <length>)
    → gives the byte length of the allocated extent

DATA_BACKREF lines (inside EXTENT_ITEM blocks):
    extent data backref root <root_id> objectid <inode> offset <file_offset>
    → links the extent to a specific inode + file offset

Output format
-------------
{
    '_parser': 'extent_tree',
    'extent_count': <int>,
    'extents': [
        {
            'logical': <int>,      # logical byte address of the extent
            'length':  <int>,      # byte length of the extent
            'refs': [
                {
                    'root_id':     <int>,
                    'inode':       <int>,
                    'file_offset': <int>,
                }
            ],
        },
        ...
    ],
    'by_inode': {
        '<inode>': [
            {'logical': <int>, 'length': <int>, 'file_offset': <int>}
        ]
    }
}

The 'by_inode' index is the fast-path used by the reconstruction engine
to look up all extents for a given inode without scanning the full list.

Example dump-tree extent fragment
----------------------------------
    item 0 key (4194304 EXTENT_ITEM 4096) itemoff 16275 itemsize 53
            refs 1 gen 7 flags DATA
            extent data backref root 5 objectid 258 offset 0 count 1
    item 1 key (8388608 EXTENT_ITEM 65536) itemoff 16200 itemsize 66
            refs 2 gen 8 flags DATA
            extent data backref root 5 objectid 259 offset 0 count 1
            extent data backref root 5 objectid 260 offset 0 count 1
"""
import re


# key (<logical> EXTENT_ITEM <length>)
_EXTENT_KEY_RE = re.compile(
    r'key\s+\(\s*(\d+)\s+EXTENT_ITEM\s+(\d+)\s*\)',
    re.IGNORECASE,
)

# flags DATA line — we skip METADATA extents
_DATA_FLAG_RE = re.compile(r'flags\s+.*\bDATA\b', re.IGNORECASE)

# extent data backref root <root_id> objectid <inode> offset <file_offset>
_BACKREF_RE = re.compile(
    r'extent\s+data\s+backref\s+root\s+(\d+)\s+'
    r'objectid\s+(\d+)\s+offset\s+(\d+)',
    re.IGNORECASE,
)


def parse(raw_data: str) -> dict:
    """Parse dump-tree extent output.

    Returns a dict with 'extents' list and 'by_inode' index.
    """
    lines = raw_data.splitlines()
    extents: list = []
    by_inode: dict = {}

    i = 0
    while i < len(lines):
        key_match = _EXTENT_KEY_RE.search(lines[i])
        if key_match:
            logical = int(key_match.group(1))
            length = int(key_match.group(2))

            # Scan ahead (up to 40 lines) for flags + backrefs
            block_end = min(i + 40, len(lines))
            block = lines[i + 1: block_end]

            # Skip metadata extents — we only need DATA
            is_data = any(_DATA_FLAG_RE.search(bl) for bl in block[:6])
            if not is_data:
                i += 1
                continue

            refs: list = []
            for bl in block:
                bm = _BACKREF_RE.search(bl)
                if bm:
                    ref = {
                        'root_id': int(bm.group(1)),
                        'inode': int(bm.group(2)),
                        'file_offset': int(bm.group(3)),
                    }
                    refs.append(ref)
                    # Build by_inode index
                    inode_key = str(ref['inode'])
                    by_inode.setdefault(inode_key, []).append({
                        'logical': logical,
                        'length': length,
                        'file_offset': ref['file_offset'],
                    })
                # Stop when we hit the next EXTENT_ITEM key
                elif _EXTENT_KEY_RE.search(bl):
                    break

            extents.append({
                'logical': logical,
                'length': length,
                'refs': refs,
            })

        i += 1

    return {
        '_parser': 'extent_tree',
        'extent_count': len(extents),
        'extents': extents,
        'by_inode': by_inode,
    }
