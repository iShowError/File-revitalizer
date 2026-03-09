import secrets

from django.db import models
from django.contrib.auth.models import User


# ---------------------------------------------------------------------------
# New models — Phase 1: deductive recovery engine
# ---------------------------------------------------------------------------

class RecoveryCase(models.Model):
    """Top-level recovery case with a strict state machine lifecycle.

    State transitions (enforced in views):
        CREATED → SCANNING → ANALYZED → RECOVERING → COMPLETE
                                      ↘ FAILED (from any state)
    """

    STATE_CREATED = 'CREATED'
    STATE_SCANNING = 'SCANNING'
    STATE_ANALYZED = 'ANALYZED'
    STATE_RECOVERING = 'RECOVERING'
    STATE_VERIFYING = 'VERIFYING'
    STATE_COMPLETE = 'COMPLETE'
    STATE_FAILED = 'FAILED'

    STATE_CHOICES = [
        (STATE_CREATED,    'Created'),
        (STATE_SCANNING,   'Scanning'),
        (STATE_ANALYZED,   'Analyzed'),
        (STATE_RECOVERING, 'Recovering'),
        (STATE_VERIFYING,  'Verifying'),
        (STATE_COMPLETE,   'Complete'),
        (STATE_FAILED,     'Failed'),
    ]

    # Valid forward transitions
    TRANSITIONS = {
        STATE_CREATED:    [STATE_SCANNING,   STATE_FAILED],
        STATE_SCANNING:   [STATE_ANALYZED,   STATE_FAILED],
        STATE_ANALYZED:   [STATE_RECOVERING, STATE_FAILED],
        STATE_RECOVERING: [STATE_VERIFYING,  STATE_FAILED],
        STATE_VERIFYING:  [STATE_COMPLETE,   STATE_FAILED],
        STATE_COMPLETE:   [],
        STATE_FAILED:     [],
    }

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recovery_cases')
    title = models.CharField(max_length=255, help_text='Human-readable case name')
    device_path = models.CharField(max_length=500, help_text='e.g. /dev/sdb or /dev/sdb1')
    filesystem_uuid = models.CharField(max_length=36, null=True, blank=True)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=STATE_CREATED)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'recovery_cases'
        ordering = ['-created_at']

    def __str__(self):
        return f'Case #{self.pk} [{self.state}] — {self.title}'

    def can_transition_to(self, new_state):
        """Return True if transition from current state to new_state is allowed."""
        return new_state in self.TRANSITIONS.get(self.state, [])

    def transition_to(self, new_state):
        """Advance the state machine; raises ValueError on illegal transition."""
        if not self.can_transition_to(new_state):
            raise ValueError(
                f'Illegal transition: {self.state} → {new_state}. '
                f'Allowed: {self.TRANSITIONS.get(self.state, [])}'
            )
        self.state = new_state
        self.save(update_fields=['state', 'updated_at'])


class Artifact(models.Model):
    """Raw metadata dump attached to a RecoveryCase.

    Each artifact stores the raw output from a BTRFS inspection command
    (e.g. dump-super, btrfs-find-root) plus the parsed structured result.
    """

    TYPE_SUPERBLOCK = 'superblock'
    TYPE_CHUNK_TREE = 'chunk_tree'
    TYPE_FS_TREE = 'fs_tree'
    TYPE_EXTENT_TREE = 'extent_tree'
    TYPE_FIND_ROOT = 'find_root'
    TYPE_OTHER = 'other'

    TYPE_CHOICES = [
        (TYPE_SUPERBLOCK,   'Superblock Dump'),
        (TYPE_CHUNK_TREE,   'Chunk Tree'),
        (TYPE_FS_TREE,      'FS Tree'),
        (TYPE_EXTENT_TREE,  'Extent Tree'),
        (TYPE_FIND_ROOT,    'btrfs-find-root Output'),
        (TYPE_OTHER,        'Other'),
    ]

    case = models.ForeignKey(RecoveryCase, on_delete=models.CASCADE, related_name='artifacts')
    artifact_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_OTHER)
    raw_data = models.TextField(help_text='Raw text/JSON from the BTRFS command')
    parsed_data = models.JSONField(default=dict, blank=True,
                                   help_text='Structured result after parser runs')
    source_command = models.CharField(max_length=500, blank=True, default='',
                                      help_text='Command that produced this artifact')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    parsed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'recovery_artifacts'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'Artifact [{self.artifact_type}] for Case #{self.case_id}'


class CandidateFile(models.Model):
    """A deleted file candidate reconstructed from BTRFS metadata.

    Confidence score guide:
        0.9  — single contiguous extent, header magic match
        0.7  — single extent, no magic check
        0.5  — multiple contiguous extents
        0.3  — fragmented / many extents
        +0.1  bonus if file-header magic bytes match expected type
    """

    STATUS_PENDING = 'pending'
    STATUS_RECOVERED = 'recovered'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'

    STATUS_CHOICES = [
        (STATUS_PENDING,   'Pending'),
        (STATUS_RECOVERED, 'Recovered'),
        (STATUS_FAILED,    'Failed'),
        (STATUS_SKIPPED,   'Skipped'),
    ]

    case = models.ForeignKey(RecoveryCase, on_delete=models.CASCADE, related_name='candidates')
    inode_number = models.BigIntegerField()
    reconstructed_path = models.TextField(blank=True, default='',
                                          help_text='Best-effort path from DIR_ITEM records')
    file_name = models.CharField(max_length=255, blank=True, default='')
    file_size = models.BigIntegerField(default=0)
    file_type = models.CharField(max_length=50, blank=True, default='unknown')

    # Extent metadata (first/primary extent)
    logical_address = models.BigIntegerField(null=True, blank=True,
                                             help_text='Logical byte address of first extent')
    physical_address = models.BigIntegerField(null=True, blank=True,
                                              help_text='Physical LBA (after chunk map translation)')
    extent_count = models.IntegerField(default=1)
    generation = models.BigIntegerField(null=True, blank=True)

    # All extents encoded as JSON list of {logical, physical, length} dicts
    extent_map = models.JSONField(default=list, blank=True)

    confidence = models.FloatField(default=0.0, help_text='0.0 – 1.0 recovery confidence score')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    discovered_at = models.DateTimeField(auto_now_add=True)
    recovered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'candidate_files'
        unique_together = [['case', 'inode_number']]
        ordering = ['-confidence', '-file_size']

    def __str__(self):
        name = self.file_name or f'inode-{self.inode_number}'
        return f'Candidate {name} (conf={self.confidence:.2f}) — Case #{self.case_id}'


class ChatSession(models.Model):
    """One grounded chatbot session tied to a RecoveryCase."""

    case = models.ForeignKey(RecoveryCase, on_delete=models.CASCADE, related_name='chat_sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chat_sessions'
        ordering = ['-created_at']

    def __str__(self):
        return f'ChatSession #{self.pk} for Case #{self.case_id}'


class ChatMessage(models.Model):
    """A single message in a ChatSession, with the grounded context snapshot."""

    ROLE_USER = 'user'
    ROLE_ASSISTANT = 'assistant'
    ROLE_SYSTEM = 'system'

    ROLE_CHOICES = [
        (ROLE_USER,      'User'),
        (ROLE_ASSISTANT, 'Assistant'),
        (ROLE_SYSTEM,    'System'),
    ]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    # Snapshot of case context injected into this prompt (for auditability)
    context_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at']

    def __str__(self):
        preview = self.content[:60].replace('\n', ' ')
        return f'[{self.role}] {preview}'


class AuditEvent(models.Model):
    """Immutable audit log: every state transition and agent command is recorded here.

    Records are append-only — never update or delete rows from this table.
    """

    EVENT_STATE_TRANSITION = 'state_transition'
    EVENT_ARTIFACT_UPLOAD = 'artifact_upload'
    EVENT_CANDIDATE_GENERATED = 'candidate_generated'
    EVENT_RECOVERY_COMMAND = 'recovery_command'
    EVENT_RECOVERY_RESULT = 'recovery_result'
    EVENT_CHAT = 'chat'
    EVENT_ERROR = 'error'

    EVENT_CHOICES = [
        (EVENT_STATE_TRANSITION,   'State Transition'),
        (EVENT_ARTIFACT_UPLOAD,    'Artifact Upload'),
        (EVENT_CANDIDATE_GENERATED,'Candidate Generated'),
        (EVENT_RECOVERY_COMMAND,   'Recovery Command'),
        (EVENT_RECOVERY_RESULT,    'Recovery Result'),
        (EVENT_CHAT,               'Chat'),
        (EVENT_ERROR,              'Error'),
    ]

    case = models.ForeignKey(RecoveryCase, on_delete=models.CASCADE,
                             related_name='audit_events', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    summary = models.CharField(max_length=500)
    detail = models.JSONField(default=dict, blank=True,
                              help_text='Arbitrary structured data for this event')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_events'
        ordering = ['-created_at']
        # Prevent accidental updates
        permissions = [('view_audit', 'Can view audit log')]

    def __str__(self):
        return f'[{self.event_type}] {self.summary} @ {self.created_at}'


class AgentToken(models.Model):
    """API token for authenticating the local agent with the server.

    Each token is a 40-character hex string tied to a single user.
    A user can have multiple tokens (e.g. one per machine).
    """

    key = models.CharField(
        max_length=40, unique=True, db_index=True,
        help_text='40-char hex token (generated automatically)',
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='agent_tokens',
    )
    label = models.CharField(
        max_length=100, blank=True, default='',
        help_text='Optional label (e.g. "home-server", "lab-machine")',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'agent_tokens'
        ordering = ['-created_at']

    def __str__(self):
        masked = f'{self.key[:8]}…{self.key[-4:]}'
        return f'Token {masked} ({self.user.username})'

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_hex(20)
        super().save(*args, **kwargs)


class Agent(models.Model):
    """Registered agent machine linked to a user and token.

    Tracks which machines have connected, their OS/version info,
    and when they last sent a heartbeat.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agents')
    token = models.ForeignKey(
        AgentToken, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='agents',
    )
    machine_name = models.CharField(max_length=255)
    os_info = models.CharField(max_length=255, blank=True, default='')
    agent_version = models.CharField(max_length=20, blank=True, default='')
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'agents'
        ordering = ['-registered_at']
        unique_together = [['user', 'machine_name']]

    def __str__(self):
        return f'Agent {self.machine_name} ({self.user.username})'
