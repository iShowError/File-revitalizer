"""Superblock parser for `btrfs inspect-internal dump-super` output.

Extracts the fields needed for recovery:
  - fsid (filesystem UUID)
  - generation
  - root (logical address of root tree)
  - chunk_root (logical address of chunk tree)
  - total_bytes, bytes_used
  - label
  - num_devices
  - nodesize, sectorsize, stripesize

The output of dump-super is plain text with lines like:
    fsid\t\t\t9e4e42f0-bad9-4e76-8c7e-abc123456789
    generation\t\t\t1234567
    root\t\t\t\t1234512640
    ...
"""
import re


# Regex patterns for each field we care about
_FIELD_PATTERNS = {
    'fsid':         re.compile(r'^\s*fsid\s+(\S+)', re.MULTILINE),
    'generation':   re.compile(r'^\s*generation\s+(\d+)', re.MULTILINE),
    'root':         re.compile(r'^\s*root\s+(\d+)', re.MULTILINE),
    'chunk_root':   re.compile(r'^\s*chunk_root\s+(\d+)', re.MULTILINE),
    'total_bytes':  re.compile(r'^\s*total_bytes\s+(\d+)', re.MULTILINE),
    'bytes_used':   re.compile(r'^\s*bytes_used\s+(\d+)', re.MULTILINE),
    'label':        re.compile(r'^\s*label\s+(.*)', re.MULTILINE),
    'num_devices':  re.compile(r'^\s*num_devices\s+(\d+)', re.MULTILINE),
    'nodesize':     re.compile(r'^\s*nodesize\s+(\d+)', re.MULTILINE),
    'sectorsize':   re.compile(r'^\s*sectorsize\s+(\d+)', re.MULTILINE),
    'stripesize':   re.compile(r'^\s*stripesize\s+(\d+)', re.MULTILINE),
    'magic':        re.compile(r'^\s*magic\s+(\S+)', re.MULTILINE),
    'compat_flags': re.compile(r'^\s*compat_flags\s+(\S+)', re.MULTILINE),
    'incompat_flags': re.compile(r'^\s*incompat_flags\s+(.*)', re.MULTILINE),
}

_INT_FIELDS = {
    'generation', 'root', 'chunk_root', 'total_bytes',
    'bytes_used', 'num_devices', 'nodesize', 'sectorsize', 'stripesize',
}


def parse(raw_data: str) -> dict:
    """Parse dump-super output. Returns a dict of extracted fields."""
    result: dict = {'_parser': 'superblock', '_warnings': []}

    for field, pattern in _FIELD_PATTERNS.items():
        match = pattern.search(raw_data)
        if match:
            value = match.group(1).strip()
            if field in _INT_FIELDS:
                try:
                    value = int(value)
                except ValueError:
                    result['_warnings'].append(f'Could not cast {field} to int: {value!r}')
            result[field] = value
        else:
            result[field] = None

    # Compute a human-readable storage size
    total = result.get('total_bytes')
    used = result.get('bytes_used')
    if isinstance(total, int):
        result['total_bytes_human'] = _fmt_bytes(total)
    if isinstance(used, int):
        result['bytes_used_human'] = _fmt_bytes(used)

    return result


def _fmt_bytes(n: int) -> str:
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} PiB'
