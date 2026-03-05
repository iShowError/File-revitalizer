"""list-devices command — enumerate block devices on the local machine.

Runs `lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,MODEL,SERIAL` and
renders a human-readable table. This lets the user identify the correct
device path (e.g. /dev/sdb) before running `scan`.

Falls back to plain `lsblk` output if JSON mode is unavailable on the
target system (older util-linux versions).

Output example:
    NAME    SIZE    TYPE   MOUNTPOINT   FSTYPE   MODEL
    ------  ------  -----  -----------  -------  -------------------
    sda     500G    disk
      sda1  512M    part   /boot        vfat
      sda2  499.5G  part   /            ext4
    sdb     1T      disk                         WD Blue
      sdb1  1T      part                btrfs    ← potential target
"""
import json
import subprocess
import sys


_LSBLK_COLS = 'NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,MODEL'


def _run(cmd: list, timeout: int = 15) -> tuple[bool, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout, r.stderr
    except FileNotFoundError:
        return False, '', f'Command not found: {cmd[0]}'
    except subprocess.TimeoutExpired:
        return False, '', f'Timed out: {" ".join(cmd)}'
    except Exception as exc:
        return False, '', str(exc)


def _format_json(raw_json: str) -> str:
    """Render lsblk -J output as an aligned table."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return f'[list-devices] Could not parse JSON: {exc}'

    rows: list[tuple] = []
    header = ('NAME', 'SIZE', 'TYPE', 'MOUNTPOINT', 'FSTYPE', 'MODEL')

    def _collect(devices, indent=0):
        for dev in devices:
            prefix = '  ' * indent
            name = prefix + dev.get('name', '')
            rows.append((
                name,
                dev.get('size', ''),
                dev.get('type', ''),
                dev.get('mountpoint') or '',
                dev.get('fstype') or '',
                (dev.get('model') or '').strip(),
            ))
            children = dev.get('children') or []
            _collect(children, indent + 1)

    _collect(data.get('blockdevices', []))

    if not rows:
        return '  No block devices found.'

    # Calculate column widths
    all_rows = [header] + rows
    widths = [max(len(str(r[i])) for r in all_rows) for i in range(len(header))]

    def fmt_row(row):
        return '  '.join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))

    lines = [
        fmt_row(header),
        '  '.join('-' * w for w in widths),
    ]
    for row in rows:
        lines.append(fmt_row(row))

    return '\n'.join(lines)


def run() -> bool:
    """List block devices. Returns True if at least one device was found."""
    print('\n[list-devices] Scanning block devices ...\n')

    # Try JSON mode first (util-linux >= 2.27)
    ok, out, err = _run(['lsblk', '-J', '-o', _LSBLK_COLS])

    if ok and out.strip():
        print(_format_json(out))
        print()
        return True

    # Fallback: plain lsblk
    ok, out, err = _run(['lsblk', '-o', _LSBLK_COLS])
    if ok and out.strip():
        print(out)
        return True

    print(f'[list-devices] lsblk failed: {err or "no output"}')
    print('[list-devices] Make sure util-linux is installed (apt install util-linux)')
    return False
