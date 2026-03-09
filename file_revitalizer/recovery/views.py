from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.contrib import messages
from django.http import JsonResponse, FileResponse, Http404, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
import os
import json
import tempfile
import logging

from dotenv import load_dotenv
import time
import requests
from .models import (
    RecoveryCase, Artifact, CandidateFile, ChatSession, ChatMessage, AuditEvent,
    Agent, AgentToken,
)
from .serializers import serialize_case, serialize_artifact, serialize_candidate, serialize_audit_event

logger = logging.getLogger(__name__)


def _ai_post_with_retry(url, headers, payload, timeout=60, max_retries=3):
    """POST to AI provider with exponential backoff on 429 rate-limit errors."""
    for attempt in range(max_retries):
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 429 or attempt == max_retries - 1:
            return resp
        wait = 2 ** attempt  # 1s, 2s, 4s
        logger.warning(f"AI provider rate-limited (429), retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
        time.sleep(wait)
    return resp  # unreachable, but keeps linters happy

# Create your views here.

def home(request):
    """Render the home page"""
    return render(request, 'home.html')

@login_required
def dashboard(request):
    """Render the dashboard page"""
    cases = RecoveryCase.objects.filter(user=request.user)

    context = {
        'total_cases': cases.count(),
        'active_cases': cases.filter(state__in=['SCANNING', 'RECOVERING', 'ANALYZED']).count(),
        'completed_cases': cases.filter(state='COMPLETE').count(),
        'failed_cases': cases.filter(state='FAILED').count(),
        'recent_cases': cases.order_by('-created_at')[:5],
    }

    return render(request, 'dashboard.html', context)

# Authentication Views

def login_view(request):
    """Handle user login"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
        if not email or not password:
            messages.error(request, 'Please provide both email and password.')
            return render(request, 'auth/login.html')
        
        try:
            # Find user by email
            user = User.objects.get(email=email)
            user = authenticate(request, username=user.username, password=password)
            
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {user.first_name}!')
                
                # Redirect to dashboard or requested page
                next_url = request.GET.get('next', 'dashboard')  # Changed from 'start_recovery' to 'dashboard'
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid email or password.')
                
        except User.DoesNotExist:
            messages.error(request, 'No account found with this email address.')
        except Exception as e:
            messages.error(request, 'Login failed. Please try again.')
    
    return render(request, 'auth/login.html')

def register_view(request):
    """Handle user registration"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password1', '')  # Fixed: Changed from 'password' to 'password1'
        confirm_password = request.POST.get('password2', '')  # Fixed: Changed from 'confirm_password' to 'password2'
        
        # Validation
        errors = []
        
        if not first_name:
            errors.append('First name is required.')
        if not last_name:
            errors.append('Last name is required.')
        if not email:
            errors.append('Email is required.')
        else:
            try:
                validate_email(email)
                if User.objects.filter(email=email).exists():
                    errors.append('An account with this email already exists.')
            except ValidationError:
                errors.append('Please enter a valid email address.')
        
        if not password:
            errors.append('Password is required.')
        elif len(password) < 8:
            errors.append('Password must be at least 8 characters long.')
        else:
            # Use Django's built-in password validation
            try:
                validate_password(password)
            except ValidationError as e:
                errors.extend(e.messages)
        
        if password != confirm_password:
            errors.append('Passwords do not match.')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'auth/register.html')
        
        try:
            # Create username from email
            username = email.split('@')[0]
            counter = 1
            original_username = username
            while User.objects.filter(username=username).exists():
                username = f"{original_username}{counter}"
                counter += 1
            
            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name
            )
            
            # Auto-login after registration
            user = authenticate(request, username=username, password=password)
            login(request, user)
            
            messages.success(request, f'Welcome to BTRFS Recovery, {first_name}!')
            return redirect('dashboard')  # Changed from 'start_recovery' to 'dashboard'
            
        except Exception as e:
            messages.error(request, 'Registration failed. Please try again.')
    
    return render(request, 'auth/register.html')

def logout_view(request):
    """Handle user logout"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('home')


@login_required
@csrf_exempt
def diagnose_issue(request):
    """Handle AI-based data loss diagnosis using a configurable provider."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method is allowed.'}, status=405)

    try:
        # --- Load Configuration ---
        load_dotenv(override=True)
        api_key = os.getenv("AI_PROVIDER_API_KEY")
        api_url_template = os.getenv("AI_PROVIDER_API_URL")
        model = os.getenv("AI_PROVIDER_MODEL")

        if not all([api_key, api_url_template, model]):
            logger.error("AI provider environment variables are not fully configured.")
            return JsonResponse({'error': 'AI service is not configured.'}, status=500)

        # --- Get User Input ---
        data = json.loads(request.body)
        user_prompt = data.get('prompt')
        if not user_prompt:
            return JsonResponse({'error': 'Prompt is missing.'}, status=400)

        # --- Prepare Prompt and Headers ---
        full_prompt = f"""You are an expert data recovery technician named 'Revitalizer AI'. A user is describing their data loss problem. Based on their description, provide a professional and helpful analysis in three distinct sections. Use markdown for formatting.
1.  **Diagnosis:** A brief, technical diagnosis of the likely problem.
2.  **Recovery Chance:** An estimated recovery probability (e.g., High, Medium, Low) with a short explanation.
3.  **Recommended Next Step:** A clear next step, which should always guide the user towards using the FileRevitalizer application.
Keep the tone helpful, reassuring, and professional.
User's problem: "{user_prompt}"
"""
        headers = {
            'Content-Type': 'application/json',
        }
        
        # --- Build Provider-Specific Payload and URL ---
        if "openrouter" in api_url_template:
            # OpenRouter uses a bearer token
            headers['Authorization'] = f"Bearer {api_key}"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": full_prompt}]
            }
            api_url = api_url_template
        elif "google" in api_url_template:
            # Google Gemini uses an API key in the URL
            payload = {
                "contents": [{"role": "user", "parts": [{"text": full_prompt}]}]
            }
            api_url = api_url_template.format(api_key=api_key)
        else:
            # Default to a generic bearer token format
            headers['Authorization'] = f"Bearer {api_key}"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": full_prompt}]
            }
            api_url = api_url_template

        # --- Make API Call (with retry on 429) ---
        response = _ai_post_with_retry(api_url, headers, payload)
        if not response.ok:
            provider_error = response.text
            try:
                provider_payload = response.json()
                provider_error = provider_payload.get('error', {}).get('message', provider_error)
            except Exception:
                pass
            logger.error(f"AI API request failed ({response.status_code}): {provider_error}")
            if response.status_code == 429:
                return JsonResponse({'error': 'The AI service is temporarily busy. Please wait a moment and try again.'}, status=429)
            return JsonResponse({'error': f'AI provider error ({response.status_code}): {provider_error}'}, status=502)

        result = response.json()

        # --- Process Response ---
        if "openrouter" in api_url_template:
            text = result['choices'][0]['message']['content']
        elif "google" in api_url_template:
            text = result['candidates'][0]['content']['parts'][0]['text']
        else: # A generic guess for other providers
            text = result.get('choices', [{}])[0].get('message', {}).get('content', 'Could not parse response.')

        return JsonResponse({'response': text})

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON in request body.'}, status=400)
    except requests.exceptions.RequestException as e:
        logger.error(f"AI API request failed: {e}")
        return JsonResponse({'error': f'Failed to communicate with AI service: {e}'}, status=502)
    except (KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI response: {e}. Response: {result}")
        return JsonResponse({'error': 'Invalid response from AI service.'}, status=500)
    except Exception as e:
        logger.error(f"An unexpected error occurred in diagnose_issue: {e}")
        return JsonResponse({'error': 'An internal server error occurred.'}, status=500)


# ===========================================================================
# Phase 2 — Recovery Case REST API
# ===========================================================================

def _audit(case, user, event_type, summary, detail=None):
    """Helper: append one AuditEvent row."""
    AuditEvent.objects.create(
        case=case,
        user=user,
        event_type=event_type,
        summary=summary,
        detail=detail or {},
    )


@login_required
@csrf_exempt
def case_list_create(request):
    """GET /api/cases/         → list caller's cases (newest first)
    POST /api/cases/         → create a new RecoveryCase
    """
    if request.method == 'GET':
        cases = RecoveryCase.objects.filter(user=request.user).order_by('-created_at')
        return JsonResponse({'cases': [serialize_case(c) for c in cases]})

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON.'}, status=400)

        title = data.get('title', '').strip()
        device_path = data.get('device_path', '').strip()
        if not title or not device_path:
            return JsonResponse({'error': 'title and device_path are required.'}, status=400)

        case = RecoveryCase.objects.create(
            user=request.user,
            title=title,
            device_path=device_path,
            filesystem_uuid=data.get('filesystem_uuid', ''),
            notes=data.get('notes', ''),
        )
        _audit(case, request.user, AuditEvent.EVENT_STATE_TRANSITION,
               f'Case #{case.pk} created in state CREATED',
               {'device_path': device_path})
        return JsonResponse({'case': serialize_case(case)}, status=201)

    return JsonResponse({'error': 'Method not allowed.'}, status=405)


@login_required
@csrf_exempt
def case_detail(request, case_id):
    """GET /api/cases/<id>/   → return case details + artifact/candidate counts."""
    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    data = serialize_case(case)
    data['artifact_count'] = case.artifacts.count()
    data['candidate_count'] = case.candidates.count()
    return JsonResponse({'case': data})


@login_required
@csrf_exempt
def case_transition(request, case_id):
    """POST /api/cases/<id>/transition/
    Body: { "state": "SCANNING" }
    Advances the state machine and records an AuditEvent.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    new_state = data.get('state', '').strip().upper()
    if not new_state:
        return JsonResponse({'error': '"state" is required.'}, status=400)

    old_state = case.state
    try:
        case.transition_to(new_state)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    _audit(case, request.user, AuditEvent.EVENT_STATE_TRANSITION,
           f'Case #{case.pk} transitioned to {new_state}',
           {'previous_state': old_state, 'new_state': new_state})
    return JsonResponse({'case': serialize_case(case)})


@login_required
@csrf_exempt
def artifact_upload(request, case_id):
    """POST /api/cases/<id>/artifacts/
    Body: {
        "artifact_type": "superblock",
        "raw_data": "<text from btrfs command>",
        "source_command": "btrfs inspect-internal dump-super /dev/sdb"  (optional)
    }
    Saves the artifact and schedules parsing (sync for now; async later).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    artifact_type = data.get('artifact_type', Artifact.TYPE_OTHER)
    raw_data = data.get('raw_data', '')
    if not raw_data:
        return JsonResponse({'error': '"raw_data" is required.'}, status=400)

    artifact = Artifact.objects.create(
        case=case,
        artifact_type=artifact_type,
        raw_data=raw_data,
        source_command=data.get('source_command', ''),
    )

    _audit(case, request.user, AuditEvent.EVENT_ARTIFACT_UPLOAD,
           f'Artifact [{artifact_type}] uploaded for Case #{case.pk}',
           {'artifact_id': artifact.pk, 'artifact_type': artifact_type})

    # Trigger parser (will be fully wired in Phase 4 — artifact pipeline)
    try:
        from .parsers import parse_artifact
        parse_artifact(artifact)
    except ImportError:
        pass  # Parsers not yet implemented — silently skip
    except Exception as parse_err:
        logger.warning(f'Parser failed for artifact {artifact.pk}: {parse_err}')

    return JsonResponse({'artifact': serialize_artifact(artifact)}, status=201)


@login_required
def candidate_list(request, case_id):
    """GET /api/cases/<id>/candidates/
    Optional query params: ?min_confidence=0.5&status=pending
    """
    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    qs = case.candidates.all()

    min_conf = request.GET.get('min_confidence')
    if min_conf:
        try:
            qs = qs.filter(confidence__gte=float(min_conf))
        except ValueError:
            pass

    status_filter = request.GET.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    return JsonResponse({'candidates': [serialize_candidate(c) for c in qs]})


@login_required
@csrf_exempt
def update_candidate_status(request, case_id, candidate_id):
    """PATCH /api/cases/<id>/candidates/<cid>/
    Mark a candidate as 'skipped' or 'failed'. Does not allow setting
    'recovered' here — that is done exclusively via recover_file.
    """
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    candidate = get_object_or_404(CandidateFile, pk=candidate_id, case=case)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    new_status = data.get('status', '').strip()
    allowed = {CandidateFile.STATUS_SKIPPED, CandidateFile.STATUS_FAILED}
    if new_status not in allowed:
        return JsonResponse(
            {'error': f"Status must be one of: {', '.join(sorted(allowed))}"},
            status=400,
        )

    old_status = candidate.status
    candidate.status = new_status
    candidate.save(update_fields=['status'])

    _audit(case, request.user, AuditEvent.EVENT_RECOVERY_COMMAND,
           f'Candidate #{candidate.pk} ({candidate.file_name}) marked {new_status}',
           {'candidate_id': candidate.pk, 'old_status': old_status, 'new_status': new_status})

    return JsonResponse({'candidate': serialize_candidate(candidate)})


@login_required
@csrf_exempt
def recover_file(request, case_id, candidate_id):
    """POST /api/cases/<id>/recover/<candidate_id>/
    Generates recovery commands and returns them + renders result page URL.
    Full agent execution bridge in Phase 6.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    candidate = get_object_or_404(CandidateFile, pk=candidate_id, case=case)

    if candidate.status == CandidateFile.STATUS_RECOVERED:
        return JsonResponse({'error': 'File already recovered.'}, status=400)

    from .command_generator import generate_all_commands
    strategies = generate_all_commands(
        candidate=candidate,
        device=case.device_path,
    )

    _audit(case, request.user, AuditEvent.EVENT_RECOVERY_COMMAND,
           f'Recovery commands generated for candidate #{candidate.pk} ({candidate.file_name})',
           {'candidate_id': candidate.pk, 'inode': candidate.inode_number,
            'strategy_types': [s['type'] for s in strategies]})

    return JsonResponse({
        'message': 'Recovery commands generated.',
        'candidate': serialize_candidate(candidate),
        'strategies': strategies,
        'result_url': f'/cases/{case_id}/recover/{candidate_id}/result/',
    }, status=200)


@login_required
def audit_log(request, case_id):
    """GET /api/cases/<id>/audit/   → chronological audit trail for a case."""
    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    events = case.audit_events.order_by('created_at')
    return JsonResponse({'events': [serialize_audit_event(e) for e in events]})


# ===========================================================================
# Phase 5 — Candidate Table
# ===========================================================================

@login_required
@csrf_exempt
def generate_candidates(request, case_id):
    """POST /api/cases/<id>/generate-candidates/
    Runs the reconstruction engine against the case’s parsed artifacts
    and upserts CandidateFile rows.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)

    from .reconstruction import reconstruct_candidates
    result = reconstruct_candidates(case)

    _audit(case, request.user, AuditEvent.EVENT_CANDIDATE_GENERATED,
           f'Candidate generation: created={result["created"]} updated={result["updated"]}',
           result)

    return JsonResponse(result)


@login_required
def candidates_view(request, case_id):
    """GET /cases/<id>/candidates/  → Rendered candidate table UI."""
    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    candidates = case.candidates.order_by('-confidence', '-file_size')

    # Collect unique file types for the filter dropdown
    file_types = sorted(
        set(c.file_type for c in candidates if c.file_type and c.file_type != 'unknown')
    )

    return render(request, 'recovery/candidates.html', {
        'case': case,
        'candidates': candidates,
        'file_types': file_types,
    })


# ===========================================================================
# Phase 6 — One-File Recovery Result
# ===========================================================================

@login_required
def recovery_result_view(request, case_id, candidate_id):
    """GET /cases/<id>/recover/<candidate_id>/result/
    Renders the recovery result page with generated shell commands.
    """
    import json as json_mod
    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    candidate = get_object_or_404(CandidateFile, pk=candidate_id, case=case)

    from .command_generator import generate_all_commands
    strategies = generate_all_commands(
        candidate=candidate,
        device=case.device_path,
    )

    # Pre-serialise commands list for JS copy-to-clipboard
    commands_json = json_mod.dumps([s.get('commands', []) for s in strategies])

    return render(request, 'recovery/recovery_result.html', {
        'case': case,
        'candidate': candidate,
        'strategies': strategies,
        'commands_json': commands_json,
    })


# ===========================================================================
# Phase 7 — Grounded Chatbot
# ===========================================================================

@login_required
def chat_view(request, case_id):
    """GET /cases/<id>/chat/  → Render the grounded chatbot UI."""
    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)

    # Get or create a ChatSession for this user+case
    session, _ = ChatSession.objects.get_or_create(
        case=case, user=request.user
    )

    history = session.messages.order_by('created_at')
    artifacts = case.artifacts.order_by('-uploaded_at')
    top_candidate = case.candidates.order_by('-confidence').first()

    return render(request, 'recovery/chat.html', {
        'case': case,
        'session_id': session.pk,
        'history': history,
        'artifacts': artifacts,
        'candidate_count': case.candidates.count(),
        'top_candidate': top_candidate,
    })


@login_required
@csrf_exempt
def chat_message(request, case_id):
    """POST /api/cases/<id>/chat/
    Body: { "message": "how do I recover this file?", "session_id": 1 }
    Returns: { "response": "..." }

    Injects live case context into the system prompt before calling the AI.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    user_message = data.get('message', '').strip()
    if not user_message:
        return JsonResponse({'error': '"message" is required.'}, status=400)

    session_id = data.get('session_id')
    if session_id:
        chat_session = get_object_or_404(ChatSession, pk=session_id, case=case)
    else:
        chat_session, _ = ChatSession.objects.get_or_create(case=case, user=request.user)

    # Build grounded system prompt
    from .context_builder import build_system_prompt, build_context
    system_prompt = build_system_prompt(case)
    context_snapshot = build_context(case)

    # Persist user message
    ChatMessage.objects.create(
        session=chat_session,
        role=ChatMessage.ROLE_USER,
        content=user_message,
        context_snapshot=context_snapshot,
    )

    # Build conversation history (last 10 messages for context window)
    recent_messages = list(
        chat_session.messages.order_by('-created_at')[:10]
    )[::-1]
    conversation = [
        {'role': msg.role, 'content': msg.content}
        for msg in recent_messages
        if msg.role in (ChatMessage.ROLE_USER, ChatMessage.ROLE_ASSISTANT)
    ]

    # Call AI provider (same pattern as diagnose_issue)
    load_dotenv(override=True)
    api_key = os.environ.get('AI_PROVIDER_API_KEY', '')
    api_url = os.environ.get('AI_PROVIDER_API_URL', '')
    model = os.environ.get('AI_PROVIDER_MODEL', 'google/gemma-3-12b-it:free')

    if not api_key or not api_url:
        return JsonResponse({'error': 'AI provider not configured.'}, status=503)

    messages_payload = [
        {'role': 'system', 'content': system_prompt},
        *conversation,
    ]

    is_openrouter = 'openrouter' in api_url
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    if is_openrouter:
        headers['HTTP-Referer'] = 'https://file-revitalizer.local'
        headers['X-Title'] = 'File Revitalizer'

    payload = {'model': model, 'messages': messages_payload}

    try:
        resp = _ai_post_with_retry(api_url, headers, payload, timeout=60)

        if not resp.ok:
            if resp.status_code == 429:
                return JsonResponse({'error': 'The AI service is temporarily busy. Please wait a moment and try again.'}, status=429)
            err_msg = resp.text[:300]
            try:
                err_msg = resp.json().get('error', {}).get('message', err_msg)
            except Exception:
                pass
            raise ValueError(f'AI provider error {resp.status_code}: {err_msg}')

        result = resp.json()
        ai_response = (
            result.get('choices', [{}])[0]
                  .get('message', {})
                  .get('content', 'Could not parse AI response.')
        )

    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error(f'Chat AI call failed: {e}')
        return JsonResponse({'error': str(e)}, status=502)

    # Persist assistant response
    ChatMessage.objects.create(
        session=chat_session,
        role=ChatMessage.ROLE_ASSISTANT,
        content=ai_response,
        context_snapshot={},
    )

    _audit(case, request.user, AuditEvent.EVENT_CHAT,
           f'Chat message in session #{chat_session.pk}',
           {'session_id': chat_session.pk, 'message_preview': user_message[:100]})

    return JsonResponse({'response': ai_response, 'session_id': chat_session.pk})


# ===========================================================================
# Browser HTML views — Cases list and Case detail
# ===========================================================================

@login_required
def cases_list_html(request):
    """GET /cases/  → Render the case list page."""
    cases = RecoveryCase.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'recovery/cases_list.html', {'cases': cases})


@login_required
def case_detail_html(request, case_id):
    """GET /cases/<id>/  → Render the case detail page."""
    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)
    allowed_transitions = RecoveryCase.TRANSITIONS.get(case.state, [])
    artifacts = case.artifacts.order_by('-uploaded_at')
    audit_events = case.audit_events.order_by('-created_at')[:5]
    return render(request, 'recovery/case_detail.html', {
        'case': case,
        'allowed_transitions': allowed_transitions,
        'artifacts': artifacts,
        'audit_events': audit_events,
        'candidate_count': case.candidates.count(),
    })


# ---------------------------------------------------------------------------
# Agent API — Recovery result reporting
# ---------------------------------------------------------------------------

@login_required
@csrf_exempt
def recovery_result_api(request, case_id):
    """POST /api/cases/<id>/recovery-result/

    Called by the local agent after executing recovery commands.
    Body: {
        "candidate_id": int,
        "results": [{"command": str, "returncode": int, "stdout": str,
                     "stderr": str, "blocked": bool}, ...],
        "all_ok": bool
    }
    Updates the CandidateFile status and logs an AuditEvent.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    case = get_object_or_404(RecoveryCase, pk=case_id, user=request.user)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    candidate_id = data.get('candidate_id')
    results = data.get('results', [])
    all_ok = data.get('all_ok', False)

    if candidate_id is None:
        return JsonResponse({'error': '"candidate_id" is required.'}, status=400)

    candidate = get_object_or_404(
        CandidateFile, pk=candidate_id, case=case,
    )

    if all_ok:
        candidate.status = CandidateFile.STATUS_RECOVERED
        candidate.recovered_at = timezone.now()
    else:
        candidate.status = CandidateFile.STATUS_FAILED
    candidate.save(update_fields=['status', 'recovered_at'])

    _audit(
        case, request.user, AuditEvent.EVENT_RECOVERY_RESULT,
        f'Recovery {"succeeded" if all_ok else "failed"} for candidate #{candidate_id}',
        {
            'candidate_id': candidate_id,
            'all_ok': all_ok,
            'command_count': len(results),
            'results_summary': [
                {
                    'command': r.get('command', '')[:200],
                    'returncode': r.get('returncode'),
                    'blocked': r.get('blocked', False),
                }
                for r in results[:20]
            ],
        },
    )

    return JsonResponse({
        'status': 'recorded',
        'candidate_status': candidate.status,
    }, status=200)


# ---------------------------------------------------------------------------
# Agent health endpoint
# ---------------------------------------------------------------------------
@csrf_exempt
def agent_health(request):
    """GET /api/agent/health/ — lightweight ping for the agent.
    Requires token auth (middleware sets request.user).
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    return JsonResponse({
        'status': 'ok',
        'server_version': '0.2.1',
        'user': request.user.username,
        'timestamp': timezone.now().isoformat(),
    })


# ---------------------------------------------------------------------------
# Agent registration & heartbeat
# ---------------------------------------------------------------------------
@csrf_exempt
def agent_register(request):
    """POST /api/agent/register/ — register or update an agent machine.
    Requires token auth.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    machine_name = data.get('machine_name', '').strip()
    if not machine_name:
        return JsonResponse({'error': '"machine_name" is required.'}, status=400)

    # Resolve the AgentToken used for this request (set by middleware)
    token_obj = None
    if getattr(request, 'is_token_auth', False):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Token '):
            key = auth_header[6:].strip()
            token_obj = AgentToken.objects.filter(key=key).first()

    agent, created = Agent.objects.update_or_create(
        user=request.user,
        machine_name=machine_name,
        defaults={
            'token': token_obj,
            'os_info': data.get('os_info', '')[:255],
            'agent_version': data.get('agent_version', '')[:20],
            'last_heartbeat': timezone.now(),
            'is_active': True,
        },
    )

    return JsonResponse({
        'agent_id': agent.pk,
        'status': 'registered' if created else 'updated',
    }, status=201 if created else 200)


@csrf_exempt
def agent_heartbeat(request):
    """POST /api/agent/heartbeat/ — update the agent's last_heartbeat.
    Requires token auth.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    now = timezone.now()
    updated = Agent.objects.filter(
        user=request.user, is_active=True,
    ).update(last_heartbeat=now)

    if not updated:
        return JsonResponse({'error': 'No registered agent found.'}, status=404)

    return JsonResponse({
        'status': 'ok',
        'server_time': now.isoformat(),
    })
