# BTRFS Filesystem Detection and Analysis
import os
import subprocess
import json
import uuid
from pathlib import Path

class BTRFSDetector:
    """Detect and analyze BTRFS filesystem accessibility"""
    
    def __init__(self, filesystem_path):
        self.filesystem_path = filesystem_path
        self.detection_result = {}
    
    def detect_and_analyze(self):
        """Main detection and analysis method"""
        try:
            # Step 1: Check if path exists
            if not self._check_path_exists():
                return self._create_error_result("Path does not exist")
            
            # Step 2: Determine if mounted or unmounted
            mount_status = self._check_mount_status()
            
            # Step 3: Try different detection methods based on mount status
            if mount_status['is_mounted']:
                return self._analyze_mounted_filesystem(mount_status)
            else:
                return self._analyze_unmounted_device()
                
        except Exception as e:
            return self._create_error_result(f"Detection failed: {str(e)}")
    
    def _check_path_exists(self):
        """Check if the provided path exists"""
        return os.path.exists(self.filesystem_path)
    
    def _check_mount_status(self):
        """Check if filesystem is mounted and where"""
        try:
            # Check if it's a mount point
            if os.path.ismount(self.filesystem_path):
                return {
                    'is_mounted': True,
                    'mount_point': self.filesystem_path,
                    'device': self._get_device_from_mount(self.filesystem_path)
                }
            
            # Check if it's a device that's mounted somewhere
            if self.filesystem_path.startswith('/dev/'):
                mount_point = self._get_mount_point_from_device(self.filesystem_path)
                if mount_point:
                    return {
                        'is_mounted': True,
                        'mount_point': mount_point,
                        'device': self.filesystem_path
                    }
            
            # Check if it's a directory in a mounted filesystem
            if os.path.isdir(self.filesystem_path):
                mount_point = self._find_mount_point(self.filesystem_path)
                if mount_point and self._is_btrfs_mount(mount_point):
                    return {
                        'is_mounted': True,
                        'mount_point': mount_point,
                        'device': self._get_device_from_mount(mount_point)
                    }
            
            return {'is_mounted': False, 'mount_point': None, 'device': self.filesystem_path}
            
        except Exception as e:
            return {'is_mounted': False, 'mount_point': None, 'device': None, 'error': str(e)}
    
    def _analyze_mounted_filesystem(self, mount_status):
        """Analyze mounted BTRFS filesystem using python-btrfs"""
        try:
            # Try to import python-btrfs dynamically to avoid import warnings
            python_btrfs_available = False
            btrfs_module = None
            FileSystem = None
            
            try:
                # Use importlib to dynamically import btrfs modules
                import importlib
                btrfs_module = importlib.import_module('btrfs')
                btrfs_ctree = importlib.import_module('btrfs.ctree')
                FileSystem = getattr(btrfs_ctree, 'FileSystem')
                python_btrfs_available = True
            except (ImportError, AttributeError, ModuleNotFoundError):
                python_btrfs_available = False
            
            result = {
                'success': True,
                'type': 'mounted',
                'mount_point': mount_status['mount_point'],
                'device': mount_status['device'],
                'recommended_method': 'python_btrfs' if python_btrfs_available else 'manual_dd',
                'python_btrfs_available': python_btrfs_available
            }
            
            if python_btrfs_available:
                # Use python-btrfs for analysis
                try:
                    with FileSystem(mount_status['mount_point']) as fs:
                        fs_info = fs.fs_info()
                        result.update({
                            'uuid': str(fs_info.fsid),
                            'total_bytes': fs_info.total_bytes,
                            'bytes_used': fs_info.bytes_used,
                            'node_size': getattr(fs_info, 'nodesize', 16384),
                            'sector_size': getattr(fs_info, 'sectorsize', 4096),
                            'analysis_method': 'python_btrfs'
                        })
                except Exception as e:
                    result['python_btrfs_error'] = str(e)
                    result['recommended_method'] = 'manual_dd'
            else:
                # Fallback to manual detection
                btrfs_info = self._get_btrfs_info_manual(mount_status['mount_point'])
                result.update(btrfs_info)
                result['analysis_method'] = 'manual_detection'
            
            return result
            
        except Exception as e:
            return self._create_error_result(f"Mounted filesystem analysis failed: {str(e)}")
    
    def _analyze_unmounted_device(self):
        """Analyze unmounted device using available tools"""
        try:
            # Check if it's a valid block device
            if not self.filesystem_path.startswith('/dev/'):
                return self._create_error_result("Unmounted analysis requires a device path (e.g., /dev/sda1)")
            
            # Try to get BTRFS info from unmounted device
            btrfs_info = self._detect_btrfs_on_device(self.filesystem_path)
            
            if btrfs_info.get('is_btrfs'):
                # Check available recovery tools
                tools_available = self._check_recovery_tools()
                
                recommended_method = 'btrfscue' if tools_available['btrfscue'] else 'manual_dd'
                
                result = {
                    'success': True,
                    'type': 'unmounted',
                    'device': self.filesystem_path,
                    'recommended_method': recommended_method,
                    'tools_available': tools_available,
                    'analysis_method': 'device_detection'
                }
                result.update(btrfs_info)
                
                return result
            else:
                return self._create_error_result("Device does not appear to contain a BTRFS filesystem")
                
        except Exception as e:
            return self._create_error_result(f"Unmounted device analysis failed: {str(e)}")
    
    def _get_device_from_mount(self, mount_point):
        """Get device path from mount point"""
        try:
            result = subprocess.run(['findmnt', '-n', '-o', 'SOURCE', mount_point], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return None
    
    def _get_mount_point_from_device(self, device):
        """Get mount point from device path"""
        try:
            result = subprocess.run(['findmnt', '-n', '-o', 'TARGET', device], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return None
    
    def _find_mount_point(self, path):
        """Find the mount point for a given path"""
        path = os.path.abspath(path)
        while not os.path.ismount(path):
            parent = os.path.dirname(path)
            if parent == path:  # Reached root
                break
            path = parent
        return path if os.path.ismount(path) else None
    
    def _is_btrfs_mount(self, mount_point):
        """Check if mount point is a BTRFS filesystem"""
        try:
            result = subprocess.run(['findmnt', '-n', '-o', 'FSTYPE', mount_point], 
                                  capture_output=True, text=True)
            return result.returncode == 0 and 'btrfs' in result.stdout.strip()
        except:
            return False
    
    def _get_btrfs_info_manual(self, mount_point):
        """Get BTRFS info using manual commands"""
        info = {}
        try:
            # Try to get filesystem info using btrfs command
            result = subprocess.run(['btrfs', 'filesystem', 'show', mount_point], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                # Parse output for UUID and other info
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'uuid:' in line.lower():
                        uuid_part = line.split('uuid:')[-1].strip()
                        info['uuid'] = uuid_part
                        break
            
            # Try to get filesystem stats
            result = subprocess.run(['btrfs', 'filesystem', 'usage', mount_point], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                # Parse output for size information
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Device size:' in line:
                        size_str = line.split(':')[-1].strip()
                        info['total_bytes'] = self._parse_size_string(size_str)
                    elif 'Used:' in line:
                        used_str = line.split(':')[-1].strip()
                        info['bytes_used'] = self._parse_size_string(used_str)
                        
        except Exception as e:
            info['manual_detection_error'] = str(e)
        
        return info
    
    def _detect_btrfs_on_device(self, device):
        """Detect if device contains BTRFS filesystem"""
        try:
            # Use blkid to detect filesystem type
            result = subprocess.run(['blkid', '-p', '-s', 'TYPE', '-s', 'UUID', device], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0:
                output = result.stdout.strip()
                is_btrfs = 'TYPE="btrfs"' in output
                
                uuid_match = None
                if 'UUID=' in output:
                    uuid_part = output.split('UUID="')[1].split('"')[0]
                    uuid_match = uuid_part
                
                return {
                    'is_btrfs': is_btrfs,
                    'uuid': uuid_match,
                    'detection_output': output
                }
            
            return {'is_btrfs': False, 'detection_output': result.stderr}
            
        except Exception as e:
            return {'is_btrfs': False, 'error': str(e)}
    
    def _check_recovery_tools(self):
        """Check availability of recovery tools"""
        tools = {
            'python_btrfs': False,
            'btrfscue': False,
            'btrfs_tools': False,
            'dd': False
        }
        
        # Check python-btrfs
        try:
            # Use importlib to avoid import warnings
            import importlib
            importlib.import_module('btrfs')
            tools['python_btrfs'] = True
        except (ImportError, ModuleNotFoundError):
            pass
        
        # Check btrfscue
        try:
            result = subprocess.run(['which', 'btrfscue'], capture_output=True)
            tools['btrfscue'] = result.returncode == 0
        except:
            pass
        
        # Check btrfs tools
        try:
            result = subprocess.run(['which', 'btrfs'], capture_output=True)
            tools['btrfs_tools'] = result.returncode == 0
        except:
            pass
        
        # Check dd
        try:
            result = subprocess.run(['which', 'dd'], capture_output=True)
            tools['dd'] = result.returncode == 0
        except:
            pass
        
        return tools
    
    def _parse_size_string(self, size_str):
        """Parse size string like '100.00GiB' to bytes"""
        try:
            size_str = size_str.strip()
            if size_str.endswith('GiB'):
                return int(float(size_str[:-3]) * 1024**3)
            elif size_str.endswith('MiB'):
                return int(float(size_str[:-3]) * 1024**2)
            elif size_str.endswith('KiB'):
                return int(float(size_str[:-3]) * 1024)
            elif size_str.endswith('TiB'):
                return int(float(size_str[:-3]) * 1024**4)
            else:
                # Try to parse as plain number
                return int(float(size_str))
        except:
            return 0
    
    def _create_error_result(self, error_message):
        """Create standardized error result"""
        return {
            'success': False,
            'error': error_message,
            'type': 'error',
            'recommended_method': None
        }
