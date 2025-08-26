from django.db import models
from django.contrib.auth.models import User
import uuid
import json

def generate_session_id():
    """Generate a unique session ID for recovery sessions"""
    return str(uuid.uuid4())

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
    session_data = models.JSONField(default=dict)  # Analysis results storage
    
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
