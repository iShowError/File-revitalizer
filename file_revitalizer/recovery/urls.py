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
    
    # AI diagnosis endpoint (used by homepage)
    path('api/diagnose/', views.diagnose_issue, name='diagnose_issue'),

    # -----------------------------------------------------------------------
    # Phase 2 — Recovery Case REST API
    # -----------------------------------------------------------------------
    path('api/cases/', views.case_list_create, name='api_case_list_create'),
    path('api/cases/<int:case_id>/', views.case_detail, name='api_case_detail'),
    path('api/cases/<int:case_id>/transition/', views.case_transition, name='api_case_transition'),
    path('api/cases/<int:case_id>/artifacts/', views.artifact_upload, name='api_artifact_upload'),
    path('api/cases/<int:case_id>/candidates/', views.candidate_list, name='api_candidate_list'),
    path('api/cases/<int:case_id>/candidates/<int:candidate_id>/', views.update_candidate_status, name='api_update_candidate_status'),
    path('api/cases/<int:case_id>/recover/<int:candidate_id>/', views.recover_file, name='api_recover_file'),
    path('api/cases/<int:case_id>/audit/', views.audit_log, name='api_audit_log'),
    path('api/cases/<int:case_id>/recovery-result/', views.recovery_result_api, name='api_recovery_result'),
    path('api/cases/<int:case_id>/verify/<int:candidate_id>/', views.verify_candidate, name='api_verify_candidate'),
    path('api/cases/<int:case_id>/report/', views.case_report_api, name='api_case_report'),

    # -----------------------------------------------------------------------
    # Agent health endpoint
    # -----------------------------------------------------------------------
    path('api/agent/health/', views.agent_health, name='api_agent_health'),
    path('api/agent/register/', views.agent_register, name='api_agent_register'),
    path('api/agent/heartbeat/', views.agent_heartbeat, name='api_agent_heartbeat'),

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
    path('cases/<int:case_id>/report/', views.case_report_view, name='case_report_view'),
]
