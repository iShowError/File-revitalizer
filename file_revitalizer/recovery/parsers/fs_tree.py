"""FS tree parser for `btrfs inspect-internal dump-tree -t fs` output.

Extracts two record types from the BTRFS FS tree:

1. INODE_ITEM records — file metadata (size, timestamps, link count)
2. DIR_ITEM / DIR_INDEX records — directory entries (name → inode mapping)

These are combined to produce a reconstructed path table:
    { inode_number: { 'path': '/some/dir/file.txt', 'size': 4096, ... } }

This table is the foundation of CandidateFile reconstruction in Phase 5.

Example dump-tree fs output fragment:
        item 3 key (256 INODE_ITEM 0) itemoff 15844 itemsize 160
                inode generation 6 transid 7 size 4096 nbytes 4096 ...
                nlink 1 uid 1000 gid 1000 ...
        item 5 key (256 DIR_ITEM 2570604837) itemoff 15642 itemsize 74
                location key (257 INODE_ITEM 0) type FILE
                namelen 7 datalen 0 name: myfile.txt
"""
import re


_INODE_KEY_RE = re.compile(
    r'key\s+\(\s*(\d+)\s+INODE_ITEM\s+0\s*\)',
    re.IGNORECASE,
)
_INODE_DETAIL_RE = re.compile(
    r'size\s+(\d+).*?nlink\s+(\d+)',
    re.IGNORECASE | re.DOTALL,
)
_DIR_KEY_RE = re.compile(
    r'key\s+\(\s*(\d+)\s+DIR_(?:ITEM|INDEX)\s+\d+\s*\)',
    re.IGNORECASE,
)
_DIR_TARGET_RE = re.compile(
    r'location key\s+\(\s*(\d+)\s+INODE_ITEM\s+0\s*\)\s+type\s+(\w+)',
    re.IGNORECASE,
)
_DIR_NAME_RE = re.compile(r'name:\s*(.+)', re.IGNORECASE)
_EXTENT_DATA_RE = re.compile(
    r'key\s+\(\s*(\d+)\s+EXTENT_DATA\s+(\d+)\s*\)',
    re.IGNORECASE,
)
_DISK_BYTENR_RE = re.compile(r'disk bytenr\s+(\d+)', re.IGNORECASE)
_DISK_NUM_BYTES_RE = re.compile(r'disk num bytes\s+(\d+)', re.IGNORECASE)


def parse(raw_data: str) -> dict:
    """Parse dump-tree fs output. Returns inodes, dir_entries, extent_refs."""
    lines = raw_data.splitlines()

    inodes: dict = {}          # inode_num → {size, nlink, extents:[]}
    dir_entries: list = []     # [{parent_inode, child_inode, name, type}]
    extent_refs: list = []     # [{inode, file_offset, disk_bytenr, length}]

    i = 0
    while i < len(lines):
        line = lines[i]

        # ── INODE_ITEM ──────────────────────────────────────────────────────
        inode_match = _INODE_KEY_RE.search(line)
        if inode_match:
            inode_num = int(inode_match.group(1))
            # Look ahead for size/nlink
            detail_text = '\n'.join(lines[i:i+5])
            dm = _INODE_DETAIL_RE.search(detail_text)
            if dm:
                inodes[inode_num] = {
                    'inode': inode_num,
                    'size': int(dm.group(1)),
                    'nlink': int(dm.group(2)),
                    'extents': [],
                }
            else:
                inodes.setdefault(inode_num, {
                    'inode': inode_num, 'size': 0, 'nlink': 0, 'extents': [],
                })
            i += 1
            continue

        # ── DIR_ITEM / DIR_INDEX ────────────────────────────────────────────
        dir_match = _DIR_KEY_RE.search(line)
        if dir_match:
            parent_inode = int(dir_match.group(1))
            # Look ahead for target inode and name
            lookahead = '\n'.join(lines[i:i+8])
            target_m = _DIR_TARGET_RE.search(lookahead)
            name_m = _DIR_NAME_RE.search(lookahead)
            if target_m and name_m:
                dir_entries.append({
                    'parent_inode': parent_inode,
                    'child_inode': int(target_m.group(1)),
                    'entry_type': target_m.group(2).upper(),
                    'name': name_m.group(1).strip(),
                })
            i += 1
            continue

        # ── EXTENT_DATA ─────────────────────────────────────────────────────
        ext_match = _EXTENT_DATA_RE.search(line)
        if ext_match:
            inode_num = int(ext_match.group(1))
            file_offset = int(ext_match.group(2))
            lookahead = '\n'.join(lines[i:i+8])
            bytenr_m = _DISK_BYTENR_RE.search(lookahead)
            num_bytes_m = _DISK_NUM_BYTES_RE.search(lookahead)
            if bytenr_m and num_bytes_m:
                disk_bytenr = int(bytenr_m.group(1))
                length = int(num_bytes_m.group(1))
                if disk_bytenr > 0 and length > 0:  # 0 = inline/hole
                    ref = {
                        'inode': inode_num,
                        'file_offset': file_offset,
                        'disk_bytenr': disk_bytenr,
                        'length': length,
                    }
                    extent_refs.append(ref)
                    if inode_num in inodes:
                        inodes[inode_num]['extents'].append(ref)
            i += 1
            continue

        i += 1

    # Build path table using dir_entries
    path_table = _build_paths(inodes, dir_entries)

    return {
        '_parser': 'fs_tree',
        'inode_count': len(inodes),
        'dir_entry_count': len(dir_entries),
        'extent_ref_count': len(extent_refs),
        'inodes': inodes,
        'dir_entries': dir_entries,
        'extent_refs': extent_refs,
        'path_table': path_table,
    }


def _build_paths(inodes: dict, dir_entries: list) -> dict:
    """Build inode→path mapping from dir_entries.

    Returns { inode_num: '/reconstructed/path/file.txt' }
    """
    # Build child→[(parent, name)] mapping
    child_to_parents: dict = {}
    for entry in dir_entries:
        child = entry['child_inode']
        if child not in child_to_parents:
            child_to_parents[child] = []
        child_to_parents[child].append((entry['parent_inode'], entry['name']))

    path_table: dict = {}
    visited: set = set()

    def resolve(inode: int, depth: int = 0) -> str:
        if depth > 40:
            return '/<deep>'
        if inode in visited:
            return f'/<cycle:{inode}>'
        visited.add(inode)
        parents = child_to_parents.get(inode)
        if not parents:
            return '/' if inode == 5 else f'/<orphan:{inode}>'
        parent_inode, name = parents[0]
        if parent_inode == inode:
            return f'/{name}'  # root of a subvolume
        parent_path = resolve(parent_inode, depth + 1)
        visited.discard(inode)
        return f'{parent_path.rstrip("/")}/{name}'

    for inode_num in inodes:
        path_table[inode_num] = resolve(inode_num)

    return path_table
