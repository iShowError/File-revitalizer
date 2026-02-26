from django.contrib import admin
from .models import (
    BTRFSRecoverySession, RecoveryStep, RecoverableFile, BTRFSAnalysis, UserProfile,
    RecoveryCase, Artifact, CandidateFile, ChatSession, ChatMessage, AuditEvent,
)


# ── Legacy models ────────────────────────────────────────────────────────────

@admin.register(BTRFSRecoverySession)
class BTRFSRecoverySessionAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'user', 'filesystem_path', 'status', 'created_at')
    list_filter = ('status', 'filesystem_type', 'recovery_method')
    search_fields = ('session_id', 'user__username', 'filesystem_path')
    readonly_fields = ('session_id', 'created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(RecoveryStep)
class RecoveryStepAdmin(admin.ModelAdmin):
    list_display = ('session', 'step_number', 'step_name', 'status')
    list_filter = ('status',)
    ordering = ('session', 'step_number')


@admin.register(RecoverableFile)
class RecoverableFileAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'session', 'file_size', 'recovery_confidence', 'recovery_status')
    list_filter = ('recovery_status', 'file_type')
    search_fields = ('file_name', 'file_path')
    ordering = ('-recovery_confidence',)


@admin.register(BTRFSAnalysis)
class BTRFSAnalysisAdmin(admin.ModelAdmin):
    list_display = ('analysis_type', 'session', 'objectid', 'confidence_score', 'is_recoverable')
    list_filter = ('analysis_type', 'is_recoverable')
    ordering = ('-confidence_score',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'preferred_recovery_method', 'total_sessions', 'files_recovered')
    search_fields = ('user__username',)


# ── Phase 1: new deductive recovery models ───────────────────────────────────

@admin.register(RecoveryCase)
class RecoveryCaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'user', 'device_path', 'state', 'created_at')
    list_filter = ('state',)
    search_fields = ('title', 'user__username', 'device_path', 'filesystem_uuid')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(Artifact)
class ArtifactAdmin(admin.ModelAdmin):
    list_display = ('id', 'case', 'artifact_type', 'source_command', 'uploaded_at', 'parsed_at')
    list_filter = ('artifact_type',)
    search_fields = ('case__id', 'source_command')
    readonly_fields = ('uploaded_at', 'parsed_at')
    ordering = ('-uploaded_at',)


@admin.register(CandidateFile)
class CandidateFileAdmin(admin.ModelAdmin):
    list_display = ('id', 'case', 'file_name', 'file_size', 'confidence', 'status', 'discovered_at')
    list_filter = ('status', 'file_type')
    search_fields = ('file_name', 'reconstructed_path')
    readonly_fields = ('discovered_at', 'recovered_at')
    ordering = ('-confidence', '-file_size')


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'case', 'user', 'created_at')
    search_fields = ('user__username',)
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'role', 'created_at')
    list_filter = ('role',)
    readonly_fields = ('created_at',)
    ordering = ('session', 'created_at')


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'case', 'user', 'event_type', 'summary', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('summary', 'user__username')
    readonly_fields = ('created_at', 'case', 'user', 'event_type', 'summary', 'detail')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False  # Audit log is append-only via code, not admin UI

    def has_change_permission(self, request, obj=None):
        return False  # Immutable
