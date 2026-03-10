"""Integration tests for agent commands with mocked subprocess and HTTP calls."""
import io
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock, call

from commands import execute, scan, upload


# Redirect stdout during tests to avoid cp1252 encoding errors on Windows
# from Unicode characters (✓, ✗) in agent print statements.
def _quiet(func):
    """Decorator that silences stdout during a test."""
    def wrapper(*args, **kwargs):
        old = sys.stdout
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        try:
            return func(*args, **kwargs)
        finally:
            sys.stdout = old
    return wrapper


# ---------------------------------------------------------------------------
# Execute integration tests
# ---------------------------------------------------------------------------

class ExecuteRunTests(unittest.TestCase):
    """Tests for execute.run() with mocked subprocess and requests."""

    @_quiet
    @patch('commands.execute.requests.post')
    @patch('commands.execute.subprocess.run')
    def test_successful_run_reports_results(self, mock_sub, mock_post):
        mock_sub.return_value = MagicMock(
            returncode=0, stdout='ok', stderr='',
        )
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})

        result = execute.run(
            server='http://localhost:8000',
            token='tok123',
            commands=['dd if=/dev/sdb of=/tmp/out bs=4096'],
            candidate_id=1,
            case_id=1,
        )
        self.assertTrue(result)
        mock_sub.assert_called_once()
        # Should have POSTed results + verification
        self.assertTrue(mock_post.called)

    @_quiet
    @patch('commands.execute.requests.post')
    @patch('commands.execute.subprocess.run')
    def test_blocked_command_never_calls_subprocess(self, mock_sub, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})

        result = execute.run(
            server='http://localhost:8000',
            token='tok123',
            commands=['rm -rf /'],
            candidate_id=1,
            case_id=1,
        )
        self.assertFalse(result)
        mock_sub.assert_not_called()

    @_quiet
    @patch('commands.execute.requests.post')
    @patch('commands.execute.subprocess.run')
    def test_timeout_handled_gracefully(self, mock_sub, mock_post):
        mock_sub.side_effect = subprocess.TimeoutExpired(cmd='dd', timeout=300)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})

        result = execute.run(
            server='http://localhost:8000',
            token='tok123',
            commands=['dd if=/dev/sdb of=/tmp/out bs=4096'],
            candidate_id=1,
            case_id=1,
        )
        self.assertFalse(result)

    @_quiet
    @patch('commands.execute.requests.post')
    @patch('commands.execute.subprocess.run')
    def test_all_fail_returns_false(self, mock_sub, mock_post):
        mock_sub.return_value = MagicMock(returncode=1, stdout='', stderr='error')
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})

        result = execute.run(
            server='http://localhost:8000',
            token='tok123',
            commands=['dd if=/dev/sdb of=/tmp/out', 'cat /dev/null'],
            candidate_id=1,
            case_id=1,
        )
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Scan integration tests
# ---------------------------------------------------------------------------

class ScanRunTests(unittest.TestCase):
    """Tests for scan.run() with mocked subprocess and upload."""

    @_quiet
    @patch('commands.scan.upload_raw', return_value=True)
    @patch('commands.scan._run_cmd')
    def test_scan_uploads_all_artifacts(self, mock_cmd, mock_upload):
        mock_cmd.return_value = (True, 'some btrfs output', '')

        result = scan.run(
            server='http://localhost:8000',
            token='tok123',
            device='/dev/sdb',
            case_id=1,
        )
        self.assertTrue(result)
        # 5 stages: superblock, find-root, chunk, fs, extent
        self.assertEqual(mock_upload.call_count, 5)

    @_quiet
    @patch('commands.scan.upload_raw', return_value=True)
    @patch('commands.scan._run_cmd')
    def test_scan_superblock_only(self, mock_cmd, mock_upload):
        mock_cmd.return_value = (True, 'superblock output', '')

        result = scan.run(
            server='http://localhost:8000',
            token='tok123',
            device='/dev/sdb',
            case_id=1,
            superblock_only=True,
        )
        self.assertTrue(result)
        self.assertEqual(mock_upload.call_count, 1)

    @_quiet
    def test_scan_rejects_bad_device(self):
        result = scan.run(
            server='http://localhost:8000',
            token='tok123',
            device='/tmp/evil',
            case_id=1,
        )
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Upload integration tests
# ---------------------------------------------------------------------------

class UploadRawTests(unittest.TestCase):
    """Tests for upload.upload_raw() with mocked requests."""

    @_quiet
    @patch('commands.upload.requests.post')
    def test_upload_sends_correct_payload(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)

        result = upload.upload_raw(
            server='http://localhost:8000',
            token='tok123',
            case_id=5,
            raw_data='superblock dump here',
            artifact_type='superblock',
            source_command='btrfs dump-super /dev/sdb',
        )
        self.assertTrue(result)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['artifact_type'], 'superblock')
        self.assertEqual(kwargs['json']['raw_data'], 'superblock dump here')
        self.assertEqual(kwargs['json']['source_command'], 'btrfs dump-super /dev/sdb')
        self.assertIn('Token tok123', kwargs['headers']['Authorization'])

    @_quiet
    @patch('commands.upload.requests.post')
    def test_upload_returns_false_on_server_error(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500, text='Internal Server Error')

        result = upload.upload_raw(
            server='http://localhost:8000',
            token='tok123',
            case_id=5,
            raw_data='data',
            artifact_type='superblock',
        )
        self.assertFalse(result)

    @_quiet
    @patch('commands.upload.requests.post')
    def test_upload_handles_network_error(self, mock_post):
        import requests as req
        mock_post.side_effect = req.exceptions.ConnectionError('refused')

        result = upload.upload_raw(
            server='http://localhost:8000',
            token='tok123',
            case_id=5,
            raw_data='data',
            artifact_type='superblock',
        )
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
