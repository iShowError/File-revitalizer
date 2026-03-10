"""Unit tests for agent/commands/scan.py — device path validation."""
import unittest

from commands.scan import _validate_device


class ValidateDeviceTests(unittest.TestCase):
    """Tests for the _validate_device() function."""

    # ── Valid device paths ────────────────────────────────────────────────

    def test_sda(self):
        self.assertTrue(_validate_device('/dev/sda'))

    def test_sdb1(self):
        self.assertTrue(_validate_device('/dev/sdb1'))

    def test_nvme(self):
        self.assertTrue(_validate_device('/dev/nvme0n1p2'))

    def test_loop(self):
        self.assertTrue(_validate_device('/dev/loop0'))

    def test_vda(self):
        self.assertTrue(_validate_device('/dev/vda'))

    def test_mapper(self):
        self.assertTrue(_validate_device('/dev/mapper/vg0-lv0'))

    # ── Invalid device paths ──────────────────────────────────────────────

    def test_reject_dotdot(self):
        self.assertFalse(_validate_device('/dev/../etc/passwd'))

    def test_reject_tmp(self):
        self.assertFalse(_validate_device('/tmp/not-a-device'))

    def test_reject_etc(self):
        self.assertFalse(_validate_device('/etc/passwd'))

    def test_reject_relative(self):
        self.assertFalse(_validate_device('sda'))

    def test_reject_semicolon(self):
        self.assertFalse(_validate_device('/dev/sda; rm -rf /'))

    def test_reject_empty(self):
        self.assertFalse(_validate_device(''))

    def test_reject_space(self):
        self.assertFalse(_validate_device('/dev/sda foo'))

    def test_reject_home(self):
        self.assertFalse(_validate_device('/home/user/disk.img'))


if __name__ == '__main__':
    unittest.main()
