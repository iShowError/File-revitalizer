from django.contrib import admin
from .models import (
    RecoveryCase, Artifact, CandidateFile, ChatSession, ChatMessage, AuditEvent,
    AgentToken, Agent,
)


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

    def has_delete_permission(self, request, obj=None):
        return False  # Audit log is immutable


@admin.register(AgentToken)
class AgentTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'masked_key', 'user', 'label', 'is_active', 'created_at', 'last_used_at')
    list_filter = ('is_active',)
    search_fields = ('user__username', 'label')
    readonly_fields = ('key', 'created_at', 'last_used_at')
    ordering = ('-created_at',)

    def masked_key(self, obj):
        return f'{obj.key[:8]}…{obj.key[-4:]}'
    masked_key.short_description = 'Token'


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ('id', 'machine_name', 'user', 'agent_version', 'is_active', 'last_heartbeat', 'registered_at')
    list_filter = ('is_active',)
    search_fields = ('machine_name', 'user__username')
    readonly_fields = ('registered_at', 'last_heartbeat')
    ordering = ('-registered_at',)
