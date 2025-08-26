# Recovery Engine - Main orchestrator for BTRFS recovery operations
import logging
from django.conf import settings
from .btrfs_detector import BTRFSDetector
from .btrfs_analyzer import BTRFSAnalyzer
from .file_discovery import FileDiscovery
from .models import BTRFSRecoverySession, BTRFSAnalysis, RecoverableFile, RecoveryStep

logger = logging.getLogger(__name__)

class RecoveryEngine:
    """
    Main recovery engine that orchestrates the complete BTRFS recovery process.
    
    This implements our hybrid recovery approach:
    1. Mounted filesystems: python-btrfs + kernel API (75-85% accuracy)
    2. Unmounted devices: btrfscue + manual parsing (65-75% accuracy)
    3. Corrupted systems: Manual metadata parsing (40-60% accuracy)
    
    Target Overall Accuracy: 68-82%
    """
    
    def __init__(self, session_id):
        self.session_id = session_id
        self.session = None
        self.detector = None
        self.analyzer = None
        self.discoverer = None
        self.detection_result = None
        self.analysis_result = None
        self.discovery_result = None
    
    def initialize_session(self):
        """Initialize recovery session from database"""
        try:
            self.session = BTRFSRecoverySession.objects.get(session_id=self.session_id)
            logger.info(f"Initialized recovery session: {self.session_id}")
            return True
        except BTRFSRecoverySession.DoesNotExist:
            logger.error(f"Recovery session not found: {self.session_id}")
            return False
    
    def run_detection_phase(self, filesystem_path):
        """
        Phase 1: Filesystem Detection
        
        Determines if filesystem is mounted/unmounted and selects optimal recovery method.
        Updates session with detection results.
        """
        try:
            logger.info(f"Starting detection phase for: {filesystem_path}")
            
            # Create detector instance
            self.detector = BTRFSDetector(filesystem_path)
            
            # Run detection
            self.detection_result = self.detector.detect_and_analyze()
            
            # Update session
            if self.detection_result.get('success'):
                self.session.filesystem_path = filesystem_path
                self.session.filesystem_type = self.detection_result.get('type', 'detected')
                self.session.filesystem_uuid = self.detection_result.get('uuid')
                self.session.mount_point = self.detection_result.get('mount_point')
                self.session.current_step = 1
                self.session.status = 'active'
                self.session.save()
                
                # Create recovery step record
                RecoveryStep.objects.create(
                    session=self.session,
                    step_number=1,
                    step_name='detection',
                    status='completed',
                    result_data=self.detection_result
                )
                
                logger.info(f"Detection completed successfully: {self.detection_result.get('type')}")
                return self.detection_result
            else:
                self.session.status = 'failed'
                self.session.save()
                
                RecoveryStep.objects.create(
                    session=self.session,
                    step_number=1,
                    step_name='detection',
                    status='failed',
                    error_message=self.detection_result.get('error'),
                    result_data=self.detection_result
                )
                
                logger.error(f"Detection failed: {self.detection_result.get('error')}")
                return self.detection_result
                
        except Exception as e:
            logger.error(f"Detection phase exception: {str(e)}")
            return {
                'success': False,
                'error': f'Detection failed: {str(e)}',
                'type': 'error'
            }
    
    def run_analysis_phase(self):
        """
        Phase 2: Filesystem Analysis
        
        Analyzes BTRFS metadata using the method determined in detection phase.
        Creates BTRFSAnalysis record with detailed filesystem information.
        """
        try:
            logger.info(f"Starting analysis phase for session: {self.session_id}")
            
            if not self.detection_result or not self.detection_result.get('success'):
                return {
                    'success': False,
                    'error': 'Cannot run analysis without successful detection'
                }
            
            # Create analyzer instance
            self.analyzer = BTRFSAnalyzer(self.detection_result)
            
            # Run analysis
            self.analysis_result = self.analyzer.analyze_metadata()
            
            # Update session
            if self.analysis_result.get('success'):
                self.session.current_step = 2
                self.session.save()
                
                # Create BTRFSAnalysis record
                analysis_record = BTRFSAnalysis.objects.create(
                    session=self.session,
                    analysis_method=self.analysis_result.get('method'),
                    filesystem_uuid=self.analysis_result.get('metadata_info', {}).get('uuid'),
                    total_bytes=self.analysis_result.get('metadata_info', {}).get('total_bytes', 0),
                    bytes_used=self.analysis_result.get('metadata_info', {}).get('bytes_used', 0),
                    node_size=self.analysis_result.get('metadata_info', {}).get('node_size', 0),
                    sector_size=self.analysis_result.get('metadata_info', {}).get('sector_size', 0),
                    subvolume_count=len(self.analysis_result.get('subvolumes', [])),
                    snapshot_count=len(self.analysis_result.get('snapshots', [])),
                    raw_metadata=self.analysis_result
                )
                
                # Create recovery step record
                RecoveryStep.objects.create(
                    session=self.session,
                    step_number=2,
                    step_name='analysis',
                    status='completed',
                    result_data=self.analysis_result
                )
                
                logger.info(f"Analysis completed using method: {self.analysis_result.get('method')}")
                return self.analysis_result
            else:
                self.session.status = 'failed'
                self.session.save()
                
                RecoveryStep.objects.create(
                    session=self.session,
                    step_number=2,
                    step_name='analysis',
                    status='failed',
                    error_message=self.analysis_result.get('error'),
                    result_data=self.analysis_result
                )
                
                logger.error(f"Analysis failed: {self.analysis_result.get('error')}")
                return self.analysis_result
                
        except Exception as e:
            logger.error(f"Analysis phase exception: {str(e)}")
            return {
                'success': False,
                'error': f'Analysis failed: {str(e)}',
                'method': 'error'
            }
    
    def run_discovery_phase(self):
        """
        Phase 3: File Discovery
        
        Discovers recoverable files using the analysis results.
        Creates RecoverableFile records for each discovered file.
        """
        try:
            logger.info(f"Starting discovery phase for session: {self.session_id}")
            
            if not self.analysis_result or not self.analysis_result.get('success'):
                return {
                    'success': False,
                    'error': 'Cannot run discovery without successful analysis'
                }
            
            # Create file discoverer instance
            self.discoverer = FileDiscovery(self.detection_result, self.analysis_result)
            
            # Run file discovery
            self.discovery_result = self.discoverer.discover_files()
            
            # Update session
            if self.discovery_result.get('success'):
                self.session.current_step = 3
                self.session.total_files = self.discovery_result.get('stats', {}).get('total_files', 0)
                self.session.save()
                
                # Create RecoverableFile records
                files_created = 0
                for file_info in self.discovery_result.get('files', []):
                    try:
                        RecoverableFile.objects.create(
                            session=self.session,
                            file_path=file_info.get('path', file_info.get('name', 'unknown')),
                            file_name=file_info.get('name', 'unknown'),
                            file_size=file_info.get('size', 0),
                            file_type=file_info.get('type', 'unknown'),
                            recovery_confidence=self._map_confidence_to_score(file_info.get('recovery_confidence', 'medium')),
                            is_recoverable=file_info.get('recovery_confidence', 'medium') != 'estimated',
                            metadata=file_info
                        )
                        files_created += 1
                    except Exception as e:
                        logger.warning(f"Failed to create RecoverableFile record: {str(e)}")
                
                # Update session stats
                self.session.recoverable_files = files_created
                self.session.confidence_score = self._calculate_overall_confidence()
                self.session.save()
                
                # Create recovery step record
                RecoveryStep.objects.create(
                    session=self.session,
                    step_number=3,
                    step_name='discovery',
                    status='completed',
                    result_data=self.discovery_result
                )
                
                logger.info(f"Discovery completed: {files_created} files discovered")
                return self.discovery_result
            else:
                self.session.status = 'failed'
                self.session.save()
                
                RecoveryStep.objects.create(
                    session=self.session,
                    step_number=3,
                    step_name='discovery',
                    status='failed',
                    error_message=self.discovery_result.get('error'),
                    result_data=self.discovery_result
                )
                
                logger.error(f"Discovery failed: {self.discovery_result.get('error')}")
                return self.discovery_result
                
        except Exception as e:
            logger.error(f"Discovery phase exception: {str(e)}")
            return {
                'success': False,
                'error': f'Discovery failed: {str(e)}',
                'files': [],
                'stats': {}
            }
    
    def get_recovery_status(self):
        """Get current recovery status and progress"""
        try:
            session = BTRFSRecoverySession.objects.get(session_id=self.session_id)
            
            # Get completed steps
            completed_steps = RecoveryStep.objects.filter(
                session=session,
                status='completed'
            ).order_by('step_number')
            
            # Calculate progress
            progress_percentage = (session.current_step / 4) * 100
            
            status = {
                'session_id': session.session_id,
                'current_step': session.current_step,
                'progress_percentage': progress_percentage,
                'status': session.status,
                'filesystem_path': session.filesystem_path,
                'filesystem_type': session.filesystem_type,
                'total_files': session.total_files,
                'recoverable_files': session.recoverable_files,
                'confidence_score': session.confidence_score,
                'created_at': session.created_at.isoformat(),
                'updated_at': session.updated_at.isoformat(),
                'completed_steps': [
                    {
                        'step_number': step.step_number,
                        'step_name': step.step_name,
                        'status': step.status,
                        'completed_at': step.completed_at.isoformat() if step.completed_at else None
                    }
                    for step in completed_steps
                ]
            }
            
            return status
            
        except BTRFSRecoverySession.DoesNotExist:
            return {
                'error': 'Session not found',
                'session_id': self.session_id
            }
    
    def _map_confidence_to_score(self, confidence_str):
        """Map confidence string to numeric score"""
        confidence_map = {
            'high': 85,
            'medium': 65,
            'low': 40,
            'estimated': 25,
            'unknown': 20
        }
        return confidence_map.get(confidence_str.lower(), 50)
    
    def _calculate_overall_confidence(self):
        """Calculate overall recovery confidence based on method and results"""
        try:
            # Base confidence on detection and analysis methods
            base_confidence = 50
            
            if self.detection_result:
                if self.detection_result.get('type') == 'mounted':
                    base_confidence = 75  # Mounted filesystems have higher success rate
                elif self.detection_result.get('type') == 'unmounted':
                    base_confidence = 60  # Unmounted devices are more challenging
                else:
                    base_confidence = 45  # Unknown/corrupted systems
            
            if self.analysis_result:
                method = self.analysis_result.get('method', '')
                if method == 'python_btrfs':
                    base_confidence += 10  # Best method available
                elif method == 'btrfscue':
                    base_confidence += 5   # Good alternative
                elif method == 'btrfs_tools':
                    base_confidence += 3   # Standard tools
                else:
                    base_confidence -= 5   # Manual/fallback methods
            
            # Cap confidence at realistic levels
            return min(max(base_confidence, 20), 90)
            
        except Exception:
            return 50  # Default confidence
    
    def get_session_summary(self):
        """Get comprehensive session summary for reporting"""
        try:
            session = BTRFSRecoverySession.objects.get(session_id=self.session_id)
            
            summary = {
                'session_info': {
                    'id': session.session_id,
                    'filesystem_path': session.filesystem_path,
                    'filesystem_type': session.filesystem_type,
                    'status': session.status,
                    'created_at': session.created_at.isoformat(),
                    'updated_at': session.updated_at.isoformat()
                },
                'recovery_stats': {
                    'total_files': session.total_files or 0,
                    'recoverable_files': session.recoverable_files or 0,
                    'confidence_score': session.confidence_score or 0,
                    'current_step': session.current_step
                },
                'analysis_info': {},
                'steps': [],
                'files_sample': []
            }
            
            # Get analysis information
            try:
                analysis = BTRFSAnalysis.objects.get(session=session)
                summary['analysis_info'] = {
                    'method': analysis.analysis_method,
                    'filesystem_uuid': analysis.filesystem_uuid,
                    'total_bytes': analysis.total_bytes,
                    'bytes_used': analysis.bytes_used,
                    'subvolume_count': analysis.subvolume_count,
                    'snapshot_count': analysis.snapshot_count
                }
            except BTRFSAnalysis.DoesNotExist:
                pass
            
            # Get recovery steps
            steps = RecoveryStep.objects.filter(session=session).order_by('step_number')
            summary['steps'] = [
                {
                    'number': step.step_number,
                    'name': step.step_name,
                    'status': step.status,
                    'error': step.error_message,
                    'completed_at': step.completed_at.isoformat() if step.completed_at else None
                }
                for step in steps
            ]
            
            # Get sample of recoverable files
            files = RecoverableFile.objects.filter(session=session, is_recoverable=True)[:10]
            summary['files_sample'] = [
                {
                    'name': f.file_name,
                    'path': f.file_path,
                    'size': f.file_size,
                    'type': f.file_type,
                    'confidence': f.recovery_confidence
                }
                for f in files
            ]
            
            return summary
            
        except BTRFSRecoverySession.DoesNotExist:
            return {
                'error': 'Session not found',
                'session_id': self.session_id
            }
