from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import os
import json
import tempfile
import logging
from .models import BTRFSRecoverySession, RecoveryStep, RecoverableFile, BTRFSAnalysis, UserProfile
from .recovery_engine import RecoveryEngine

logger = logging.getLogger(__name__)

# Create your views here.

def home(request):
    """Render the home page"""
    return render(request, 'home.html')

def dashboard(request):
    """Render the dashboard page"""
    return render(request, 'dashboard.html')

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
                
                # Redirect to recovery or requested page
                next_url = request.GET.get('next', 'start_recovery')
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
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
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
            
            messages.success(request, f'Welcome to BTRFS Recovery, {first_name}! Your account has been created.')
            return redirect('start_recovery')
            
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
        messages.error(request, f'Failed to initialize recovery: {str(e)}')
        return redirect('dashboard')

@login_required
def new_recovery_session(request):
    """Create a new recovery session"""
    if request.method == 'POST':
        filesystem_path = request.POST.get('filesystem_path', '').strip()
        
        if not filesystem_path:
            messages.error(request, 'Please provide a filesystem path.')
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
            'total_steps': steps.count()
        }
        
        return render(request, 'recovery/wizard.html', context)
        
    except Exception as e:
        messages.error(request, f'Recovery session error: {str(e)}')
        return redirect('start_recovery')

# API Endpoints for Recovery Process

@login_required
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
        
        # Import recovery modules (will create these next)
        from .btrfs_detector import BTRFSDetector
        
        detector = BTRFSDetector(session.filesystem_path)
        detection_result = detector.detect_and_analyze()
        
        # Update session with detection results
        session.filesystem_type = detection_result.get('type', 'detected')
        session.filesystem_uuid = detection_result.get('uuid')
        session.mount_point = detection_result.get('mount_point')
        session.recovery_method = detection_result.get('recommended_method')
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
        return JsonResponse({'error': str(e)}, status=500)

@login_required  
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
        
        # Import analysis modules (will create these next)
        from .btrfs_analyzer import BTRFSAnalyzer
        
        analyzer = BTRFSAnalyzer(session)
        analysis_result = analyzer.analyze_filesystem()
        
        # Update session with analysis results
        session.total_inodes = analysis_result.get('total_orphans', 0)
        session.recoverable_files = analysis_result.get('recoverable_count', 0)
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
        return JsonResponse({'error': str(e)}, status=500)

@login_required
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
        return JsonResponse({'error': str(e)}, status=500)

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
