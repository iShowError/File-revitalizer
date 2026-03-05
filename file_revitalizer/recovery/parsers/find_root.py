"""find-root parser for `btrfs-find-root <device>` output.

`btrfs-find-root` scans a BTRFS device for valid tree roots by reading
individual nodes and checking their generation numbers. It is the primary
tool for recovering a filesystem whose superblock no longer points to a
valid root.

Output format (two common variants)
-------------------------------------
Variant A (btrfs-find-root from btrfs-progs):
    Scanning for tree root
    found tree root at 29769728 gen 42 level 1
    found tree root at 29786112 gen 41 level 1
    Well block 0 seems great to use, found 3 roots

Variant B (older builds):
    found root at 29769728 generation 42 level 1

Both variants are handled by this parser.

Output format
-------------
{
    '_parser': 'find_root',
    'root_count': <int>,
    'roots': [
        {
            'bytenr':     <int>,   # byte offset on device
            'generation': <int>,   # BTRFS generation number
            'level':      <int>,   # tree level (0 = leaf)
        },
        ...
    ],
    'best': {                      # root with the highest generation
        'bytenr': <int>,
        'generation': <int>,
        'level': <int>,
    } | None
}

Roots are returned sorted descending by generation (highest = most recent
= most likely to be the usable root). The 'best' key is a convenience
shortcut to the first entry.
"""
import re


# Variant A:  found tree root at <bytenr> gen <gen> level <level>
_ROOT_A_RE = re.compile(
    r'found\s+tree\s+root\s+at\s+(\d+)\s+gen(?:eration)?\s+(\d+)\s+level\s+(\d+)',
    re.IGNORECASE,
)

# Variant B:  found root at <bytenr> generation <gen> level <level>
_ROOT_B_RE = re.compile(
    r'found\s+root\s+at\s+(\d+)\s+generation\s+(\d+)\s+level\s+(\d+)',
    re.IGNORECASE,
)


def parse(raw_data: str) -> dict:
    """Parse btrfs-find-root output.

    Returns a dict with 'roots' list sorted by descending generation
    and a 'best' shortcut to the most recent root.
    """
    roots: list = []
    seen_bytenrs: set = set()

    for line in raw_data.splitlines():
        match = _ROOT_A_RE.search(line) or _ROOT_B_RE.search(line)
        if match:
            bytenr = int(match.group(1))
            generation = int(match.group(2))
            level = int(match.group(3))
            # De-duplicate: same bytenr may appear across multiple scan passes
            if bytenr not in seen_bytenrs:
                seen_bytenrs.add(bytenr)
                roots.append({
                    'bytenr': bytenr,
                    'generation': generation,
                    'level': level,
                })

    # Sort by descending generation — highest gen = most recent valid root
    roots.sort(key=lambda r: r['generation'], reverse=True)

    return {
        '_parser': 'find_root',
        'root_count': len(roots),
        'roots': roots,
        'best': roots[0] if roots else None,
    }
