"""Recovery command generator — Phase 6.

Generates the shell commands needed to recover a specific file from a BTRFS
device using raw block-level access. Never executes anything locally — all
execution happens on the user's machine via the local agent.

Commands generated (in priority order):

1. dd — Always generated when a physical extent address is known.
   dd if=<device> bs=<sector_size> skip=<lba> count=<sectors> > /tmp/<name>

2. btrfs restore — Generated as a fallback when a mount point reference
   is available.
   btrfs restore -t <gen> <device> /mnt/recovery/

3. Multi-extent dd — When multiple extents are present, a shell script is
   generated that concatenates each extent in order.

Safety note: These commands are whitelisted in execute.py (Phase 8). Any
generated command MUST start with an allowed binary from ALLOWED_COMMANDS.
"""
import math
import os
import re

# Canonical whitelist — also enforced in agent/commands/execute.py
ALLOWED_COMMANDS = frozenset(['dd', 'btrfs', 'btrfs-find-root', 'btrfs-restore'])

# Default sector size used for LBA → byte translation
DEFAULT_SECTOR_SIZE = 512


def _lba(byte_offset: int, sector_size: int = DEFAULT_SECTOR_SIZE) -> int:
    """Convert a byte offset to a sector (LBA) number."""
    return byte_offset // sector_size


def _sector_count(byte_length: int, sector_size: int = DEFAULT_SECTOR_SIZE) -> int:
    """Round a byte length up to the nearest sector count."""
    return math.ceil(byte_length / sector_size)


def _safe_filename(name: str) -> str:
    """Strip dangerous characters from a filename."""
    name = os.path.basename(name)
    name = re.sub(r'[^\w.\-]', '_', name)
    return name or 'recovered_file'


def _assert_safe(commands: list) -> None:
    """Raise ValueError if any non-comment command starts with a disallowed binary.

    This is a defence-in-depth check — the primary whitelist is enforced in
    agent/commands/execute.py.  We double-check here so that a bug in the
    generator itself cannot produce a command that would pass the agent's
    filter.

    Comment lines (starting with '#') and empty lines are ignored.
    Shell utility helpers (mkdir, cat, rm, truncate, echo) are permitted.
    """
    _SHELL_UTILS = frozenset(['mkdir', 'cat', 'rm', 'truncate', 'echo'])

    for cmd in commands:
        stripped = cmd.strip()
        if not stripped or stripped.startswith('#'):
            continue
        binary = stripped.split()[0]
        binary_name = os.path.basename(binary)
        if binary_name in _SHELL_UTILS:
            continue
        if binary_name not in ALLOWED_COMMANDS:
            raise ValueError(
                f"Unsafe command rejected by whitelist: {binary_name!r}. "
                f"Allowed recovery binaries: {sorted(ALLOWED_COMMANDS)}"
            )


def generate_dd_command(candidate, device: str,
                        sector_size: int = DEFAULT_SECTOR_SIZE,
                        output_dir: str = '/tmp/recovered') -> dict:
    """Generate dd command for a CandidateFile.

    Returns a dict:
        {
            'type': 'dd_single' | 'dd_multi' | 'error',
            'commands': [str, ...],   # ordered list of shell commands
            'output_file': str,
            'warnings': [str, ...],
        }
    """
    result = {'type': None, 'commands': [], 'output_file': None, 'warnings': []}

    safe_name = _safe_filename(candidate.file_name or f'inode_{candidate.inode_number}')
    output_file = f'{output_dir}/{safe_name}'
    result['output_file'] = output_file

    extent_map = candidate.extent_map or []

    # ── Single extent ────────────────────────────────────────────────────────
    if len(extent_map) <= 1 and candidate.physical_address:
        phys = candidate.physical_address
        length = candidate.file_size or (
            extent_map[0]['length'] if extent_map else DEFAULT_SECTOR_SIZE
        )
        lba = _lba(phys, sector_size)
        count = _sector_count(length, sector_size)

        cmd = (
            f'dd if={device} bs={sector_size} '
            f'skip={lba} count={count} '
            f'> {output_file}'
        )
        result['type'] = 'dd_single'
        result['commands'] = [
            f'mkdir -p {output_dir}',
            cmd,
        ]
        if candidate.file_size and candidate.file_size != length:
            result['warnings'].append(
                f'File size ({candidate.file_size}B) may differ from extent length ({length}B). '
                'Truncate if needed: truncate -s {candidate.file_size} ' + output_file
            )
        _assert_safe(result['commands'])
        return result

    # ── Multi-extent ─────────────────────────────────────────────────────────
    sorted_extents = sorted(extent_map, key=lambda e: e.get('file_offset', 0))
    valid_extents = [e for e in sorted_extents if e.get('physical')]

    if not valid_extents:
        result['type'] = 'error'
        result['warnings'].append(
            'No physical addresses available. Upload a chunk_tree artifact first, '
            'then regenerate candidates.'
        )
        return result

    tmp_parts = []
    cmds = [f'mkdir -p {output_dir}']

    for idx, ext in enumerate(valid_extents):
        part_file = f'{output_dir}/.part_{idx}_{safe_name}'
        tmp_parts.append(part_file)
        phys = ext['physical']
        length = ext.get('length', DEFAULT_SECTOR_SIZE)
        lba = _lba(phys, sector_size)
        count = _sector_count(length, sector_size)
        cmds.append(
            f'dd if={device} bs={sector_size} skip={lba} count={count} > {part_file}'
        )

    # Concatenate: cat part0 part1 ... > output
    cmds.append(f'cat {" ".join(tmp_parts)} > {output_file}')
    # Cleanup temp parts
    cmds.append(f'rm -f {" ".join(tmp_parts)}')

    result['type'] = 'dd_multi'
    result['commands'] = cmds
    result['warnings'].append(
        f'Multi-extent recovery ({len(valid_extents)} extents). '
        'File may be corrupted if extents are not all intact.'
    )
    _assert_safe(result['commands'])
    return result


def generate_btrfs_restore_command(candidate, device: str,
                                   generation: int = None,
                                   output_dir: str = '/mnt/recovery') -> dict:
    """Generate btrfs restore command as a fallback.

    Returns a dict with 'commands' and 'warnings'.
    """
    gen_flag = f'-t {generation} ' if generation else ''
    cmds = [
        f'mkdir -p {output_dir}',
        f'btrfs restore {gen_flag}{device} {output_dir}',
        f'# Then look for: {candidate.reconstructed_path or candidate.file_name}',
    ]
    _assert_safe(cmds)
    return {
        'type': 'btrfs_restore',
        'commands': cmds,
        'output_file': f'{output_dir}/{candidate.file_name or "recovered"}',
        'warnings': [
            'btrfs restore recovers all files; filter for your target afterwards.',
        ],
    }


def generate_all_commands(candidate, device: str,
                          sector_size: int = DEFAULT_SECTOR_SIZE,
                          output_dir: str = '/tmp/recovered',
                          generation: int = None) -> list:
    """Return both dd and btrfs-restore strategies, in priority order."""
    strategies = []

    dd = generate_dd_command(candidate, device, sector_size, output_dir)
    if dd['type'] != 'error':
        strategies.append(dd)

    restore = generate_btrfs_restore_command(candidate, device, generation, '/mnt/recovery')
    strategies.append(restore)

    if not strategies:
        strategies.append({
            'type': 'error',
            'commands': [],
            'output_file': None,
            'warnings': ['Cannot generate recovery commands: no physical address or device.'],
        })

    return strategies
