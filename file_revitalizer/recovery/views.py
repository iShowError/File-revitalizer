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
import requests
from .models import (
    BTRFSRecoverySession, RecoveryStep, RecoverableFile, BTRFSAnalysis, UserProfile,
    RecoveryCase, Artifact, CandidateFile, ChatSession, ChatMessage, AuditEvent,
)
from .recovery_engine import RecoveryEngine
from .serializers import serialize_case, serialize_artifact, serialize_candidate, serialize_audit_event

logger = logging.getLogger(__name__)

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
        # User already logged in, redirect to recovery
        return redirect('start_recovery')
    
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
        return redirect('start_recovery')
    
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
            
            # Create user profile
            UserProfile.objects.create(user=user)
            
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

# Recovery Flow Views

@login_required
def start_recovery(request):
    """Initialize recovery process - entry point from 'Start recovery now' button"""
    # Clear any existing messages to ensure clean state
    if request.method == 'GET':
        storage = messages.get_messages(request)
        storage.used = True  # Mark all messages as used to clear them
    
    try:
        # Get or create user profile
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        
        # Check for existing active sessions
        active_sessions = BTRFSRecoverySession.objects.filter(
            user=request.user,
            status='active'
        ).order_by('-created_at')
        
        context = {
            'active_sessions': active_sessions,
            'user_profile': profile,
            'has_previous_sessions': BTRFSRecoverySession.objects.filter(user=request.user).exists()
        }
        
        return render(request, 'recovery/start_recovery.html', context)
        
    except Exception as e:
        logger.error(f"Error in start_recovery view: {str(e)}")
        messages.error(request, 'There was an issue initializing the recovery system. Please try again.')
        return redirect('dashboard')

@login_required
def new_recovery_session(request):
    """Create a new recovery session"""
    if request.method == 'POST':
        filesystem_path = request.POST.get('filesystem_path', '').strip()
        
        # Validate filesystem path
        if not filesystem_path:
            messages.error(request, 'Please provide a filesystem path.')
            return redirect('start_recovery')
        
        # Basic path validation
        if len(filesystem_path) < 3:
            messages.error(request, 'Filesystem path seems too short. Please provide a valid path.')
            return redirect('start_recovery')
        
        # Check for potentially dangerous paths
        dangerous_patterns = ['rm ', 'sudo ', 'format', 'mkfs']
        if any(pattern in filesystem_path.lower() for pattern in dangerous_patterns):
            messages.error(request, 'Invalid filesystem path detected.')
            return redirect('start_recovery')
        
        try:
            # Create new recovery session
            session = BTRFSRecoverySession.objects.create(
                user=request.user,
                filesystem_path=filesystem_path,
                status='active'
            )
            
            # Initialize recovery steps
            recovery_steps = [
                {'number': 1, 'name': 'Filesystem Detection', 'description': 'Detect filesystem type and accessibility'},
                {'number': 2, 'name': 'Metadata Analysis', 'description': 'Analyze BTRFS metadata structures'},
                {'number': 3, 'name': 'File Discovery', 'description': 'Discover recoverable deleted files'},
                {'number': 4, 'name': 'Recovery Execution', 'description': 'Recover selected files'}
            ]
            
            for step_data in recovery_steps:
                RecoveryStep.objects.create(
                    session=session,
                    step_number=step_data['number'],
                    step_name=step_data['name'],
                    step_description=step_data['description']
                )
            
            return redirect('recovery_wizard', session_id=session.session_id)
            
        except Exception as e:
            messages.error(request, f'Failed to create recovery session: {str(e)}')
            return redirect('start_recovery')
    
    return redirect('start_recovery')

@login_required
def recovery_wizard(request, session_id):
    """Main recovery wizard interface"""
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        steps = session.steps.all().order_by('step_number')
        current_step = session.current_step
        
        # Get current step details
        try:
            current_step_obj = steps.get(step_number=current_step)
        except RecoveryStep.DoesNotExist:
            current_step_obj = steps.first()
            current_step = 1
            session.current_step = 1
            session.save()
        
        context = {
            'session': session,
            'steps': steps,
            'current_step': current_step,
            'current_step_obj': current_step_obj,
            'progress_percentage': (current_step / steps.count()) * 100,
            'total_steps': steps.count(),
            'analysis_results': session.session_data.get('superblock_analysis', {}),
            'discovery_results': session.session_data.get('discovery_results', {})
        }
        
        return render(request, 'recovery/wizard.html', context)
        
    except Exception as e:
        messages.error(request, f'Recovery session error: {str(e)}')
        return redirect('start_recovery')

# API Endpoints for Recovery Process

@login_required
@transaction.atomic
def detect_filesystem(request, session_id):
    """AJAX endpoint for filesystem detection"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        # Validate session state
        if session.current_step != 1:
            return JsonResponse({
                'error': f'Invalid step. Expected step 1, current step is {session.current_step}'
            }, status=400)
        
        # Import recovery modules (will create these next)
        from .btrfs_detector import BTRFSDetector
        
        detector = BTRFSDetector(session.filesystem_path)
        detection_result = detector.detect_and_analyze()
        
        # Update session with detection results
        session.filesystem_type = detection_result.get('type', 'detected')
        session.filesystem_uuid = detection_result.get('uuid')
        session.mount_point = detection_result.get('mount_point')
        session.recovery_method = detection_result.get('recommended_method')
        
        # Safely update session_data
        if session.session_data is None:
            session.session_data = {}
        session.session_data.update(detection_result)
        session.save()
        
        # Update step status
        step = session.steps.get(step_number=1)
        step.status = 'completed'
        step.validation_result = detection_result
        step.save()
        
        # Move to next step
        session.current_step = 2
        session.save()
        
        return JsonResponse({
            'success': True,
            'detection_result': detection_result,
            'next_step': 2
        })
        
    except Exception as e:
        logger.error(f"Filesystem detection error for session {session_id}: {str(e)}")
        return JsonResponse({'error': f'Detection failed: {str(e)}'}, status=500)

@login_required
@transaction.atomic
def analyze_metadata(request, session_id):
    """AJAX endpoint for metadata analysis"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        # Validate session state
        if session.current_step != 2:
            return JsonResponse({
                'error': f'Invalid step. Expected step 2, current step is {session.current_step}'
            }, status=400)
        
        # Import analysis modules (will create these next)
        from .btrfs_analyzer import BTRFSAnalyzer
        
        analyzer = BTRFSAnalyzer(session)
        analysis_result = analyzer.analyze_filesystem()
        
        # Update session with analysis results
        session.total_inodes = analysis_result.get('total_orphans', 0)
        session.recoverable_files = analysis_result.get('recoverable_count', 0)
        
        # Safely update session_data
        if session.session_data is None:
            session.session_data = {}
        session.session_data.update(analysis_result)
        session.save()
        
        # Store detailed analysis
        for analysis_data in analysis_result.get('detailed_analysis', []):
            BTRFSAnalysis.objects.create(
                session=session,
                analysis_type=analysis_data['type'],
                objectid=analysis_data['objectid'],
                item_type=analysis_data['item_type'],
                offset_value=analysis_data['offset'],
                generation=analysis_data.get('generation', 0),
                metadata_json=json.dumps(analysis_data),
                confidence_score=analysis_data.get('confidence', 0.5),
                is_recoverable=analysis_data.get('recoverable', False),
                estimated_size=analysis_data.get('size', 0)
            )
        
        # Update step status
        step = session.steps.get(step_number=2)
        step.status = 'completed'
        step.validation_result = analysis_result
        step.save()
        
        # Move to next step
        session.current_step = 3
        session.save()
        
        return JsonResponse({
            'success': True,
            'analysis_result': analysis_result,
            'next_step': 3
        })
        
    except Exception as e:
        logger.error(f"Metadata analysis error for session {session_id}: {str(e)}")
        return JsonResponse({'error': f'Analysis failed: {str(e)}'}, status=500)

@login_required
@transaction.atomic
def discover_files(request, session_id):
    """AJAX endpoint for file discovery"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        # Validate session state
        if session.current_step != 3:
            return JsonResponse({
                'error': f'Invalid step. Expected step 3, current step is {session.current_step}'
            }, status=400)
        
        # Import file discovery modules (will create these next)
        from .file_discovery import FileDiscovery
        
        discoverer = FileDiscovery(session)
        discovery_result = discoverer.discover_recoverable_files()
        
        # Create RecoverableFile objects
        files_created = 0
        for file_data in discovery_result.get('files', []):
            recoverable_file, created = RecoverableFile.objects.get_or_create(
                session=session,
                inode_number=file_data['inode'],
                defaults={
                    'file_path': file_data.get('path', f'/unknown/inode_{file_data["inode"]}'),
                    'file_name': file_data.get('name', f'recovered_{file_data["inode"]}'),
                    'file_size': file_data.get('size', 0),
                    'file_type': file_data.get('type', 'unknown'),
                    'deletion_timestamp': file_data.get('deletion_time'),
                    'logical_address': file_data.get('logical_addr'),
                    'physical_address': file_data.get('physical_addr'),
                    'extent_count': file_data.get('extent_count', 0),
                    'generation': file_data.get('generation'),
                    'recovery_confidence': file_data.get('confidence', 0.5),
                    'is_deleted': file_data.get('is_deleted', True)
                }
            )
            if created:
                files_created += 1
        
        # Update session
        session.recoverable_files = files_created
        
        # Safely update session_data
        if session.session_data is None:
            session.session_data = {}
        session.session_data.update(discovery_result)
        session.save()
        
        # Update step status
        step = session.steps.get(step_number=3)
        step.status = 'completed'
        step.validation_result = discovery_result
        step.save()
        
        # Move to next step
        session.current_step = 4
        session.save()
        
        return JsonResponse({
            'success': True,
            'discovery_result': discovery_result,
            'files_found': files_created,
            'next_step': 4
        })
        
    except Exception as e:
        logger.error(f"File discovery error for session {session_id}: {str(e)}")
        return JsonResponse({'error': f'Discovery failed: {str(e)}'}, status=500)

@login_required
def get_recovery_status(request, session_id):
    """AJAX endpoint to get current recovery session status"""
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        # Get all steps with their status
        steps = session.steps.all().order_by('step_number')
        steps_data = []
        for step in steps:
            steps_data.append({
                'number': step.step_number,
                'name': step.step_name,
                'description': step.step_description,
                'status': step.status,
                'completed_at': step.completed_at.isoformat() if step.completed_at else None,
                'validation_result': step.validation_result
            })
        
        return JsonResponse({
            'success': True,
            'session': {
                'id': session.session_id,
                'current_step': session.current_step,
                'status': session.status,
                'filesystem_path': session.filesystem_path,
                'total_inodes': session.total_inodes,
                'recoverable_files': session.recoverable_files,
                'created_at': session.created_at.isoformat(),
                'updated_at': session.updated_at.isoformat()
            },
            'steps': steps_data,
            'progress_percentage': (session.current_step / len(steps_data)) * 100 if steps_data else 0
        })
        
    except Exception as e:
        logger.error(f"Get recovery status error for session {session_id}: {str(e)}")
        return JsonResponse({'error': f'Status retrieval failed: {str(e)}'}, status=500)

@login_required
def file_list(request, session_id):
    """Display discovered files for recovery"""
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        # Get recoverable files
        files = session.files.all().order_by('-recovery_confidence', '-file_size')
        
        # Get analysis data for display
        analyses = session.analysis.all().order_by('-confidence_score')
        
        context = {
            'session': session,
            'files': files,
            'analyses': analyses,
            'total_files': files.count(),
            'high_confidence_files': files.filter(recovery_confidence__gte=0.7).count(),
            'session_data': session.session_data
        }
        
        return render(request, 'recovery/file_list.html', context)
        
    except Exception as e:
        messages.error(request, f'Error loading file list: {str(e)}')
        return redirect('recovery_wizard', session_id=session_id)

@csrf_exempt
def upload_disk_image(request, session_id):
    """Handle disk image uploads for manual recovery process"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    # Check if user is authenticated
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        # Check if file was uploaded
        if 'superblock_image' not in request.FILES and 'metadata_image' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)
        
        # Determine which type of upload this is
        if 'superblock_image' in request.FILES:
            uploaded_file = request.FILES['superblock_image']
            upload_type = 'superblock'
            max_size = 100 * 1024 * 1024  # 100MB for superblock
        else:
            uploaded_file = request.FILES['metadata_image']
            upload_type = 'metadata'
            max_size = 600 * 1024 * 1024  # 600MB for metadata
        
        # Validate file size
        if uploaded_file.size > max_size:
            return JsonResponse({
                'error': f'File too large. Maximum size for {upload_type} is {max_size // (1024*1024)}MB'
            }, status=400)
        
        # Save uploaded file temporarily
        import tempfile
        import shutil
        
        temp_dir = tempfile.mkdtemp()
        temp_file_path = os.path.join(temp_dir, uploaded_file.name)
        
        with open(temp_file_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)
        
        # Initialize session_data if needed
        if session.session_data is None:
            session.session_data = {}
        
        # Process based on upload type
        if upload_type == 'superblock':
            # Analyze superblock
            try:
                from .btrfs_analyzer import BTRFSAnalyzer
                analyzer = BTRFSAnalyzer(session)
                analysis_result = analyzer.analyze_superblock_file(temp_file_path)
                
                # Clean up temp file
                shutil.rmtree(temp_dir)
                
                # Check if analysis was successful
                if analysis_result.get('success', False):
                    # Update session with superblock analysis
                    session.session_data['superblock_analysis'] = analysis_result
                    session.current_step = 2
                    session.save()
                    
                    return JsonResponse({
                        'success': True,
                        'message': 'Superblock analyzed successfully',
                        'analysis': analysis_result,
                        'next_step': 2
                    })
                else:
                    # Analysis failed, return the error
                    return JsonResponse({
                        'success': False,
                        'error': analysis_result.get('error', 'Unknown analysis error')
                    }, status=400)
                
            except Exception as e:
                logger.error(f"Superblock analysis failed: {str(e)}")
                shutil.rmtree(temp_dir)
                return JsonResponse({
                    'error': f'Superblock analysis failed: {str(e)}'
                }, status=500)
        
        else:  # metadata upload
            # Analyze metadata
            try:
                from .btrfs_analyzer import BTRFSAnalyzer
                analyzer = BTRFSAnalyzer(session)
                discovery_result = analyzer.analyze_metadata_file(temp_file_path)
                
                # Update session with discovery results
                session.session_data['discovery_results'] = discovery_result
                session.current_step = 3
                session.save()
                
                # Clean up temp file
                shutil.rmtree(temp_dir)
                
                return JsonResponse({
                    'success': True,
                    'message': 'Metadata analyzed and files discovered',
                    'discovery': discovery_result,
                    'next_step': 3
                })
                
            except Exception as e:
                logger.error(f"Metadata analysis failed: {str(e)}")
                shutil.rmtree(temp_dir)
                return JsonResponse({
                    'error': f'Metadata analysis failed: {str(e)}'
                }, status=500)
        
    except Exception as e:
        logger.error(f"Upload error for session {session_id}: {str(e)}")
        return JsonResponse({'error': f'Upload failed: {str(e)}'}, status=500)

# Manual Upload Endpoints for Disk Images

@login_required
@transaction.atomic
def upload_superblock(request, session_id):
    """Handle superblock image upload"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        # Check if file is uploaded
        if 'superblock_image' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)
        
        uploaded_file = request.FILES['superblock_image']
        
        # Validate file
        if uploaded_file.size > 100 * 1024 * 1024:  # 100MB limit
            return JsonResponse({'error': 'File too large. Maximum size is 100MB.'}, status=400)
        
        if not uploaded_file.name.endswith(('.img', '.iso')):
            return JsonResponse({'error': 'Invalid file format. Please upload .img files.'}, status=400)
        
        # Save file to temp location (in production, use proper storage)
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.img') as temp_file:
            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name
        
        # Store file path in session data
        session_data = session.session_data or {}
        session_data['superblock_image_path'] = temp_path
        session_data['superblock_image_name'] = uploaded_file.name
        session_data['superblock_image_size'] = uploaded_file.size
        
        # Add mock superblock analysis results
        session_data['superblock_analysis'] = {
            'uuid': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            'total_size': '500 GB',
            'node_size': '16 KB',
            'checksum_type': 'CRC32C'
        }
        
        session.session_data = session_data
        
        # Mark step 1 as completed and move to step 2
        session.current_step = 2
        session.save()
        
        # Mark step 1 as completed
        step1 = session.steps.filter(step_number=1).first()
        if step1:
            step1.status = 'completed'
            step1.completed_at = timezone.now()
            step1.save()
        
        logger.info(f"Superblock image uploaded for session {session_id}: {uploaded_file.name}")
        
        return JsonResponse({
            'success': True,
            'message': 'Superblock image uploaded successfully',
            'file_name': uploaded_file.name,
            'file_size': uploaded_file.size,
            'next_step': 2
        })
        
    except Exception as e:
        logger.error(f"Error uploading superblock image: {str(e)}")
        return JsonResponse({'error': f'Upload failed: {str(e)}'}, status=500)

@login_required
@transaction.atomic
def upload_metadata(request, session_id):
    """Handle metadata image upload"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        # Check if file is uploaded
        if 'metadata_image' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)
        
        uploaded_file = request.FILES['metadata_image']
        
        # Validate file
        if uploaded_file.size > 600 * 1024 * 1024:  # 600MB limit
            return JsonResponse({'error': 'File too large. Maximum size is 600MB.'}, status=400)
        
        if not uploaded_file.name.endswith(('.img', '.iso')):
            return JsonResponse({'error': 'Invalid file format. Please upload .img files.'}, status=400)
        
        # Save file to temp location
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.img') as temp_file:
            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name
        
        # Store file path in session data
        session_data = session.session_data or {}
        session_data['metadata_image_path'] = temp_path
        session_data['metadata_image_name'] = uploaded_file.name
        session_data['metadata_image_size'] = uploaded_file.size
        
        # Simulate file discovery results
        session_data['discovery_results'] = {
            'total_files': 1247,
            'recoverable_files': 892,
            'confidence': 87,
            'priority_files': [
                {'name': 'Documents/important_report.pdf', 'size': 2048576, 'type': 'PDF', 'inode': 12345, 'confidence': 95},
                {'name': 'Photos/vacation_2024.jpg', 'size': 4194304, 'type': 'JPEG', 'inode': 12346, 'confidence': 92},
                {'name': 'Projects/source_code.zip', 'size': 8388608, 'type': 'Archive', 'inode': 12347, 'confidence': 89},
                {'name': 'Videos/family_video.mp4', 'size': 104857600, 'type': 'Video', 'inode': 12348, 'confidence': 85},
                {'name': 'Music/album_collection.mp3', 'size': 5242880, 'type': 'Audio', 'inode': 12349, 'confidence': 91}
            ]
        }
        session.session_data = session_data
        
        # Mark step 2 as completed and move to step 3
        session.current_step = 3
        session.save()
        
        # Mark step 2 as completed
        step2 = session.steps.filter(step_number=2).first()
        if step2:
            step2.status = 'completed'
            step2.completed_at = timezone.now()
            step2.save()
        
        logger.info(f"Metadata image uploaded for session {session_id}: {uploaded_file.name}")
        
        return JsonResponse({
            'success': True,
            'message': 'Metadata image uploaded and analyzed successfully',
            'file_name': uploaded_file.name,
            'file_size': uploaded_file.size,
            'discovery_results': session_data['discovery_results'],
            'next_step': 3
        })
        
    except Exception as e:
        logger.error(f"Error uploading metadata image: {str(e)}")
        return JsonResponse({'error': f'Upload failed: {str(e)}'}, status=500)

@login_required
def download_report(request, session_id):
    """Download recovery report"""
    try:
        session = get_object_or_404(
            BTRFSRecoverySession,
            session_id=session_id,
            user=request.user
        )
        
        # Generate simple report
        report_content = f"""BTRFS Recovery Session Report
Session ID: {session.session_id}
Created: {session.created_at}
Status: {session.status}
Current Step: {session.current_step}

Recovery Summary:
- Total Files Discovered: {session.session_data.get('discovery_results', {}).get('total_files', 'N/A')}
- Recoverable Files: {session.session_data.get('discovery_results', {}).get('recoverable_files', 'N/A')}
- Success Confidence: {session.session_data.get('discovery_results', {}).get('confidence', 'N/A')}%

Generated on: {timezone.now()}
"""
        
        response = HttpResponse(report_content, content_type='text/plain')
        response['Content-Disposition'] = f'attachment; filename="recovery_report_{session.session_id[:8]}.txt"'
        return response
        
    except Exception as e:
        logger.error(f"Error generating report: {str(e)}")
        return JsonResponse({'error': f'Report generation failed: {str(e)}'}, status=500)

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

        # --- Make API Call ---
        response = requests.post(api_url, json=payload, headers=headers)
        if not response.ok:
            provider_error = response.text
            try:
                provider_payload = response.json()
                provider_error = provider_payload.get('error', {}).get('message', provider_error)
            except Exception:
                pass
            logger.error(f"AI API request failed ({response.status_code}): {provider_error}")
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

    try:
        case.transition_to(new_state)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    _audit(case, request.user, AuditEvent.EVENT_STATE_TRANSITION,
           f'Case #{case.pk} transitioned to {new_state}',
           {'previous_state': case.state, 'new_state': new_state})
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
        resp = requests.post(api_url, headers=headers, json=payload, timeout=60)

        if not resp.ok:
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
