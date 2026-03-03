from django.urls import path
from . import views

urlpatterns = [
    # Main pages (existing)
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Authentication URLs
    path('auth/login/', views.login_view, name='login'),
    path('auth/register/', views.register_view, name='register'),
    path('auth/logout/', views.logout_view, name='logout'),
    
    # Recovery Flow URLs
    path('recovery/start/', views.start_recovery, name='start_recovery'),
    path('recovery/new-session/', views.new_recovery_session, name='new_recovery_session'),
    path('recovery/wizard/<str:session_id>/', views.recovery_wizard, name='recovery_wizard'),
    path('recovery/files/<str:session_id>/', views.file_list, name='file_list'),
    
    # Recovery API Endpoints
    path('api/recovery/<str:session_id>/detect/', views.detect_filesystem, name='api_detect_filesystem'),
    path('api/recovery/<str:session_id>/analyze/', views.analyze_metadata, name='api_analyze_metadata'),
    path('api/recovery/<str:session_id>/discover/', views.discover_files, name='api_discover_files'),
    path('api/recovery/<str:session_id>/status/', views.get_recovery_status, name='api_get_recovery_status'),
    path('recovery/api/<str:session_id>/upload/', views.upload_disk_image, name='upload_disk_image'),
    path('recovery/api/diagnose/', views.diagnose_issue, name='diagnose_issue'),

    # -----------------------------------------------------------------------
    # Phase 2 — Recovery Case REST API
    # -----------------------------------------------------------------------
    path('api/cases/', views.case_list_create, name='api_case_list_create'),
    path('api/cases/<int:case_id>/', views.case_detail, name='api_case_detail'),
    path('api/cases/<int:case_id>/transition/', views.case_transition, name='api_case_transition'),
    path('api/cases/<int:case_id>/artifacts/', views.artifact_upload, name='api_artifact_upload'),
    path('api/cases/<int:case_id>/candidates/', views.candidate_list, name='api_candidate_list'),
    path('api/cases/<int:case_id>/recover/<int:candidate_id>/', views.recover_file, name='api_recover_file'),
    path('api/cases/<int:case_id>/audit/', views.audit_log, name='api_audit_log'),

    # -----------------------------------------------------------------------
    # Phase 5 — Candidate table
    # -----------------------------------------------------------------------
    path('api/cases/<int:case_id>/generate-candidates/', views.generate_candidates, name='api_generate_candidates'),
    path('cases/<int:case_id>/candidates/', views.candidates_view, name='candidates_view'),

    # -----------------------------------------------------------------------
    # Phase 6 — One-file recovery result page
    # -----------------------------------------------------------------------
    path('cases/<int:case_id>/recover/<int:candidate_id>/result/',
         views.recovery_result_view, name='recovery_result_view'),

    # -----------------------------------------------------------------------
    # Phase 7 — Grounded chatbot
    # -----------------------------------------------------------------------
    path('cases/<int:case_id>/chat/', views.chat_view, name='chat_view'),
    path('api/cases/<int:case_id>/chat/', views.chat_message, name='api_chat_message'),

    # -----------------------------------------------------------------------
    # Browser UI — Cases list and case detail pages
    # -----------------------------------------------------------------------
    path('cases/', views.cases_list_html, name='cases_list'),
    path('cases/<int:case_id>/', views.case_detail_html, name='case_detail'),
]
