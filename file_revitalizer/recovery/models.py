from django.db import models
from django.contrib.auth.models import User
import uuid
import json

def generate_session_id():
    """Generate a unique session ID for recovery sessions"""
    return str(uuid.uuid4())

def default_session_data():
    """Return default empty dict for session_data field"""
    return {}

# Create your models here.

class BTRFSRecoverySession(models.Model):
    """Recovery session for tracking user's BTRFS recovery process"""
    session_id = models.CharField(max_length=64, unique=True, default=generate_session_id)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    filesystem_path = models.CharField(max_length=500)  # Mount point or device path
    filesystem_uuid = models.CharField(max_length=36, null=True, blank=True)  # BTRFS filesystem UUID
    mount_point = models.CharField(max_length=500, null=True, blank=True)
    filesystem_type = models.CharField(max_length=20, choices=[
        ('mounted', 'Mounted Filesystem'),
        ('unmounted', 'Unmounted Device'),
        ('detected', 'Auto-detected')
    ], default='detected')
    
    # Session tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    current_step = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled')
    ], default='active')
    
    # Analysis results
    total_inodes = models.BigIntegerField(default=0)
    recoverable_files = models.BigIntegerField(default=0)
    session_data = models.JSONField(default=default_session_data)  # Fixed: Use function instead of lambda
    
    # Recovery method used
    recovery_method = models.CharField(max_length=20, choices=[
        ('python_btrfs', 'Python-BTRFS'),
        ('btrfscue', 'BTRFScue'),
        ('manual_dd', 'Manual DD Commands'),
        ('hybrid', 'Hybrid Approach')
    ], null=True, blank=True)
    
    class Meta:
        db_table = 'recovery_sessions'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Recovery Session {self.session_id[:8]} - {self.user.username}"

class RecoveryStep(models.Model):
    """Individual steps in the recovery process"""
    session = models.ForeignKey(BTRFSRecoverySession, on_delete=models.CASCADE, related_name='steps')
    step_number = models.IntegerField()
    step_name = models.CharField(max_length=100)
    step_description = models.TextField()
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped')
    ], default='pending')
    
    # Step data
    command_generated = models.TextField(null=True, blank=True)  # DD command if needed
    file_uploaded = models.FileField(upload_to='recovery_metadata/', null=True, blank=True)
    validation_result = models.JSONField(default=dict)
    error_message = models.TextField(null=True, blank=True)
    
    # Timestamps
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'recovery_steps'
        unique_together = ['session', 'step_number']
        ordering = ['step_number']
    
    def __str__(self):
        return f"Step {self.step_number}: {self.step_name}"

class RecoverableFile(models.Model):
    """Files discovered and available for recovery"""
    session = models.ForeignKey(BTRFSRecoverySession, on_delete=models.CASCADE, related_name='files')
    
    # File identification
    file_path = models.TextField()
    file_name = models.CharField(max_length=255)
    inode_number = models.BigIntegerField()
    
    # File metadata
    file_size = models.BigIntegerField()
    file_type = models.CharField(max_length=50)
    deletion_timestamp = models.BigIntegerField(null=True, blank=True)
    
    # BTRFS specific data
    logical_address = models.BigIntegerField(null=True, blank=True)
    physical_address = models.BigIntegerField(null=True, blank=True)
    extent_count = models.IntegerField(default=0)
    generation = models.BigIntegerField(null=True, blank=True)
    
    # Recovery information
    recovery_status = models.CharField(max_length=20, choices=[
        ('available', 'Available for Recovery'),
        ('in_progress', 'Recovery in Progress'),
        ('recovered', 'Successfully Recovered'),
        ('failed', 'Recovery Failed'),
        ('partial', 'Partially Recovered')
    ], default='available')
    
    recovery_confidence = models.FloatField()  # 0.0 - 1.0 confidence score
    is_deleted = models.BooleanField(default=False)
    
    # Recovery results
    recovered_size = models.BigIntegerField(null=True, blank=True)
    integrity_score = models.FloatField(null=True, blank=True)  # Data integrity percentage
    recovery_path = models.CharField(max_length=500, null=True, blank=True)  # Where file was recovered
    
    # Timestamps
    discovered_at = models.DateTimeField(auto_now_add=True)
    recovered_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'recoverable_files'
        unique_together = ['session', 'inode_number']
        ordering = ['-recovery_confidence', '-file_size']
    
    def __str__(self):
        return f"{self.file_name} (Inode: {self.inode_number})"

class BTRFSAnalysis(models.Model):
    """Detailed BTRFS structure analysis results"""
    session = models.ForeignKey(BTRFSRecoverySession, on_delete=models.CASCADE, related_name='analysis')
    
    # BTRFS metadata
    analysis_type = models.CharField(max_length=50, choices=[
        ('orphan_inodes', 'Orphaned Inodes'),
        ('deleted_dirs', 'Deleted Directory Entries'),
        ('orphaned_extents', 'Orphaned File Extents'),
        ('cow_nodes', 'COW Tree Nodes'),
        ('superblock', 'Superblock Analysis'),
        ('chunk_tree', 'Chunk Tree Analysis')
    ])
    
    # BTRFS key structure
    objectid = models.BigIntegerField()
    item_type = models.IntegerField()
    offset_value = models.BigIntegerField()
    generation = models.BigIntegerField()
    
    # Analysis data
    metadata_json = models.TextField()  # Detailed analysis data
    confidence_score = models.FloatField()  # Analysis confidence
    
    # Recovery potential
    is_recoverable = models.BooleanField(default=False)
    estimated_size = models.BigIntegerField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'btrfs_analysis'
        ordering = ['-confidence_score', '-created_at']
    
    def __str__(self):
        return f"{self.analysis_type} - Object {self.objectid}"

class UserProfile(models.Model):
    """Extended user profile for recovery preferences"""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    
    # User preferences
    preferred_recovery_method = models.CharField(max_length=20, choices=[
        ('automatic', 'Automatic Detection'),
        ('python_btrfs', 'Python-BTRFS Only'),
        ('manual', 'Manual Commands Only')
    ], default='automatic')
    
    # Recovery settings
    max_file_size = models.BigIntegerField(default=100*1024*1024)  # 100MB default
    auto_download = models.BooleanField(default=False)
    show_technical_details = models.BooleanField(default=False)
    
    # Statistics
    total_sessions = models.IntegerField(default=0)
    files_recovered = models.IntegerField(default=0)
    bytes_recovered = models.BigIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_profiles'
    
    def __str__(self):
        return f"Profile for {self.user.username}"


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
    STATE_COMPLETE = 'COMPLETE'
    STATE_FAILED = 'FAILED'

    STATE_CHOICES = [
        (STATE_CREATED,    'Created'),
        (STATE_SCANNING,   'Scanning'),
        (STATE_ANALYZED,   'Analyzed'),
        (STATE_RECOVERING, 'Recovering'),
        (STATE_COMPLETE,   'Complete'),
        (STATE_FAILED,     'Failed'),
    ]

    # Valid forward transitions
    TRANSITIONS = {
        STATE_CREATED:    [STATE_SCANNING,   STATE_FAILED],
        STATE_SCANNING:   [STATE_ANALYZED,   STATE_FAILED],
        STATE_ANALYZED:   [STATE_RECOVERING, STATE_FAILED],
        STATE_RECOVERING: [STATE_COMPLETE,   STATE_FAILED],
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
