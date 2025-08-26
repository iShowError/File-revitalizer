# BTRFS Metadata Analysis Engine
import os
import json
import subprocess
import struct
from datetime import datetime
from pathlib import Path

class BTRFSAnalyzer:
    """Analyze BTRFS metadata and filesystem structure"""
    
    def __init__(self, filesystem_info):
        self.filesystem_info = filesystem_info
        self.analysis_result = {}
        self.metadata_cache = {}
    
    def analyze_metadata(self):
        """Main metadata analysis method"""
        try:
            if self.filesystem_info['type'] == 'mounted':
                return self._analyze_mounted_metadata()
            else:
                return self._analyze_unmounted_metadata()
        except Exception as e:
            return self._create_error_result(f"Metadata analysis failed: {str(e)}")
    
    def _analyze_mounted_metadata(self):
        """Analyze metadata on mounted filesystem"""
        try:
            mount_point = self.filesystem_info['mount_point']
            
            # Method 1: Try python-btrfs if available
            if self.filesystem_info.get('python_btrfs_available'):
                try:
                    return self._analyze_with_python_btrfs(mount_point)
                except Exception as e:
                    # Fallback to manual analysis
                    pass
            
            # Method 2: Manual analysis using btrfs tools
            return self._analyze_with_btrfs_tools(mount_point)
            
        except Exception as e:
            return self._create_error_result(f"Mounted metadata analysis failed: {str(e)}")
    
    def _analyze_unmounted_metadata(self):
        """Analyze metadata on unmounted device"""
        try:
            device = self.filesystem_info['device']
            
            # Method 1: Try btrfscue if available
            if self.filesystem_info.get('tools_available', {}).get('btrfscue'):
                try:
                    return self._analyze_with_btrfscue(device)
                except Exception as e:
                    # Fallback to manual parsing
                    pass
            
            # Method 2: Manual metadata parsing
            return self._analyze_with_manual_parsing(device)
            
        except Exception as e:
            return self._create_error_result(f"Unmounted metadata analysis failed: {str(e)}")
    
    def _analyze_with_python_btrfs(self, mount_point):
        """Analyze using python-btrfs library"""
        try:
            # Use importlib to dynamically import btrfs modules
            import importlib
            btrfs_module = importlib.import_module('btrfs')
            btrfs_ctree = importlib.import_module('btrfs.ctree')
            FileSystem = getattr(btrfs_ctree, 'FileSystem')
            
            result = {
                'success': True,
                'method': 'python_btrfs',
                'timestamp': datetime.now().isoformat(),
                'subvolumes': [],
                'snapshots': [],
                'metadata_info': {}
            }
            
            with FileSystem(mount_point) as fs:
                # Get filesystem info
                fs_info = fs.fs_info()
                result['metadata_info'] = {
                    'uuid': str(fs_info.fsid),
                    'total_bytes': fs_info.total_bytes,
                    'bytes_used': fs_info.bytes_used,
                    'node_size': getattr(fs_info, 'nodesize', 16384),
                    'sector_size': getattr(fs_info, 'sectorsize', 4096),
                    'chunk_size': getattr(fs_info, 'chunksize', 1024*1024*1024)
                }
                
                # Get subvolumes
                try:
                    for subvol in fs.subvolumes():
                        subvol_info = {
                            'id': subvol.subvolid,
                            'path': subvol.path,
                            'uuid': str(subvol.uuid) if subvol.uuid else None,
                            'parent_uuid': str(subvol.parent_uuid) if subvol.parent_uuid else None,
                            'generation': subvol.generation,
                            'flags': subvol.flags
                        }
                        
                        # Check if it's a snapshot
                        if subvol.parent_uuid:
                            result['snapshots'].append(subvol_info)
                        else:
                            result['subvolumes'].append(subvol_info)
                except Exception as e:
                    result['subvolume_error'] = str(e)
                
                # Get chunk tree info for recovery planning
                try:
                    chunk_info = self._get_chunk_info_python_btrfs(fs)
                    result['chunk_info'] = chunk_info
                except Exception as e:
                    result['chunk_error'] = str(e)
            
            return result
            
        except ImportError:
            return self._create_error_result("python-btrfs not available")
        except Exception as e:
            return self._create_error_result(f"python-btrfs analysis failed: {str(e)}")
    
    def _analyze_with_btrfs_tools(self, mount_point):
        """Analyze using standard btrfs tools"""
        try:
            result = {
                'success': True,
                'method': 'btrfs_tools',
                'timestamp': datetime.now().isoformat(),
                'subvolumes': [],
                'snapshots': [],
                'metadata_info': {}
            }
            
            # Get subvolume list
            try:
                cmd_result = subprocess.run(['btrfs', 'subvolume', 'list', '-u', mount_point], 
                                          capture_output=True, text=True)
                if cmd_result.returncode == 0:
                    subvols = self._parse_subvolume_list(cmd_result.stdout)
                    result['subvolumes'] = subvols['subvolumes']
                    result['snapshots'] = subvols['snapshots']
            except Exception as e:
                result['subvolume_error'] = str(e)
            
            # Get filesystem usage
            try:
                cmd_result = subprocess.run(['btrfs', 'filesystem', 'usage', '-b', mount_point], 
                                          capture_output=True, text=True)
                if cmd_result.returncode == 0:
                    usage_info = self._parse_filesystem_usage(cmd_result.stdout)
                    result['metadata_info'].update(usage_info)
            except Exception as e:
                result['usage_error'] = str(e)
            
            # Get filesystem show info
            try:
                cmd_result = subprocess.run(['btrfs', 'filesystem', 'show', mount_point], 
                                          capture_output=True, text=True)
                if cmd_result.returncode == 0:
                    show_info = self._parse_filesystem_show(cmd_result.stdout)
                    result['metadata_info'].update(show_info)
            except Exception as e:
                result['show_error'] = str(e)
            
            return result
            
        except Exception as e:
            return self._create_error_result(f"btrfs tools analysis failed: {str(e)}")
    
    def _analyze_with_btrfscue(self, device):
        """Analyze using btrfscue tool"""
        try:
            result = {
                'success': True,
                'method': 'btrfscue',
                'timestamp': datetime.now().isoformat(),
                'metadata_info': {},
                'recovery_info': {}
            }
            
            # Use btrfscue to analyze filesystem structure
            try:
                cmd_result = subprocess.run(['btrfscue', '--show-info', device], 
                                          capture_output=True, text=True)
                if cmd_result.returncode == 0:
                    btrfscue_info = self._parse_btrfscue_output(cmd_result.stdout)
                    result['metadata_info'].update(btrfscue_info)
                else:
                    result['btrfscue_error'] = cmd_result.stderr
            except Exception as e:
                result['btrfscue_error'] = str(e)
            
            # Try to get recoverable file list
            try:
                cmd_result = subprocess.run(['btrfscue', '--list-files', device], 
                                          capture_output=True, text=True)
                if cmd_result.returncode == 0:
                    file_list = self._parse_btrfscue_files(cmd_result.stdout)
                    result['recovery_info']['discoverable_files'] = len(file_list)
                    result['recovery_info']['file_sample'] = file_list[:10]  # First 10 files
            except Exception as e:
                result['file_list_error'] = str(e)
            
            return result
            
        except Exception as e:
            return self._create_error_result(f"btrfscue analysis failed: {str(e)}")
    
    def _analyze_with_manual_parsing(self, device):
        """Manual metadata parsing for corrupted filesystems"""
        try:
            result = {
                'success': True,
                'method': 'manual_parsing',
                'timestamp': datetime.now().isoformat(),
                'metadata_info': {},
                'recovery_info': {}
            }
            
            # Read superblock
            try:
                superblock_info = self._read_superblock(device)
                result['metadata_info'].update(superblock_info)
            except Exception as e:
                result['superblock_error'] = str(e)
            
            # Try to find chunk tree
            try:
                chunk_info = self._find_chunk_tree(device)
                result['metadata_info']['chunk_tree_found'] = chunk_info is not None
                if chunk_info:
                    result['metadata_info']['chunk_tree_location'] = chunk_info
            except Exception as e:
                result['chunk_tree_error'] = str(e)
            
            # Estimate recovery potential
            try:
                recovery_estimate = self._estimate_recovery_potential(device, result['metadata_info'])
                result['recovery_info'].update(recovery_estimate)
            except Exception as e:
                result['recovery_estimate_error'] = str(e)
            
            return result
            
        except Exception as e:
            return self._create_error_result(f"Manual parsing failed: {str(e)}")
    
    def _get_chunk_info_python_btrfs(self, fs):
        """Get chunk information using python-btrfs"""
        try:
            # Use importlib to dynamically import btrfs module
            import importlib
            btrfs_module = importlib.import_module('btrfs')
            
            chunks = []
            for chunk in fs.chunks():
                chunk_info = {
                    'logical': chunk.logical,
                    'length': chunk.length,
                    'type': chunk.type,
                    'stripes': []
                }
                
                for stripe in chunk.stripes:
                    stripe_info = {
                        'devid': stripe.devid,
                        'offset': stripe.offset
                    }
                    chunk_info['stripes'].append(stripe_info)
                
                chunks.append(chunk_info)
            
            return {
                'total_chunks': len(chunks),
                'chunks': chunks[:20]  # First 20 chunks
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def _parse_subvolume_list(self, output):
        """Parse btrfs subvolume list output"""
        subvolumes = []
        snapshots = []
        
        lines = output.strip().split('\n')
        for line in lines:
            if not line.strip():
                continue
                
            # Parse line: ID 256 gen 7 parent 5 top level 5 path @
            parts = line.split()
            if len(parts) >= 6:
                subvol_info = {
                    'id': int(parts[1]),
                    'generation': int(parts[3]),
                    'parent_id': int(parts[5]),
                    'top_level': int(parts[9]) if len(parts) > 9 else None,
                    'path': ' '.join(parts[11:]) if len(parts) > 11 else ''
                }
                
                # Check if it's a snapshot (has uuid info or specific naming)
                if '@' in subvol_info['path'] or 'snapshot' in subvol_info['path'].lower():
                    snapshots.append(subvol_info)
                else:
                    subvolumes.append(subvol_info)
        
        return {'subvolumes': subvolumes, 'snapshots': snapshots}
    
    def _parse_filesystem_usage(self, output):
        """Parse btrfs filesystem usage output"""
        usage_info = {}
        lines = output.split('\n')
        
        for line in lines:
            line = line.strip()
            if 'Device size:' in line:
                size_str = line.split(':')[1].strip()
                usage_info['device_size'] = self._parse_size_bytes(size_str)
            elif 'Device allocated:' in line:
                size_str = line.split(':')[1].strip()
                usage_info['device_allocated'] = self._parse_size_bytes(size_str)
            elif 'Used:' in line and 'Data' in line:
                size_str = line.split('Used:')[1].strip()
                usage_info['data_used'] = self._parse_size_bytes(size_str)
        
        return usage_info
    
    def _parse_filesystem_show(self, output):
        """Parse btrfs filesystem show output"""
        show_info = {}
        lines = output.split('\n')
        
        for line in lines:
            line = line.strip()
            if 'uuid:' in line.lower():
                uuid_part = line.split('uuid:')[1].strip()
                show_info['uuid'] = uuid_part
            elif 'Label:' in line:
                label_part = line.split('Label:')[1].strip()
                show_info['label'] = label_part if label_part != 'none' else None
        
        return show_info
    
    def _parse_btrfscue_output(self, output):
        """Parse btrfscue information output"""
        info = {}
        lines = output.split('\n')
        
        for line in lines:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower().replace(' ', '_')
                value = value.strip()
                
                if 'size' in key:
                    info[key] = self._parse_size_bytes(value)
                elif 'uuid' in key:
                    info[key] = value
                else:
                    info[key] = value
        
        return info
    
    def _parse_btrfscue_files(self, output):
        """Parse btrfscue file list output"""
        files = []
        lines = output.split('\n')
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                # Parse file information from btrfscue output
                # Format may vary, adapt as needed
                files.append(line)
        
        return files
    
    def _read_superblock(self, device):
        """Read BTRFS superblock"""
        try:
            # BTRFS superblock locations: 64KB, 64MB, 256GB
            superblock_offsets = [0x10000, 0x4000000, 0x4000000000]
            
            with open(device, 'rb') as f:
                for offset in superblock_offsets:
                    try:
                        f.seek(offset)
                        data = f.read(4096)  # Superblock is 4KB
                        
                        if len(data) >= 4096:
                            # Check BTRFS magic number
                            magic = data[0x40:0x48]
                            if magic == b'_BHRfS_M':
                                return self._parse_superblock(data)
                    except:
                        continue
            
            return {'error': 'Valid superblock not found'}
            
        except Exception as e:
            return {'error': str(e)}
    
    def _parse_superblock(self, data):
        """Parse BTRFS superblock data"""
        try:
            # Extract key information from superblock
            info = {}
            
            # UUID (offset 0x20, 16 bytes)
            uuid_bytes = data[0x20:0x30]
            info['uuid'] = '-'.join([
                uuid_bytes[0:4].hex(),
                uuid_bytes[4:6].hex(),
                uuid_bytes[6:8].hex(),
                uuid_bytes[8:10].hex(),
                uuid_bytes[10:16].hex()
            ])
            
            # Total bytes (offset 0x70, 8 bytes)
            info['total_bytes'] = struct.unpack('<Q', data[0x70:0x78])[0]
            
            # Bytes used (offset 0x78, 8 bytes)
            info['bytes_used'] = struct.unpack('<Q', data[0x78:0x80])[0]
            
            # Node size (offset 0x84, 4 bytes)
            info['node_size'] = struct.unpack('<I', data[0x84:0x88])[0]
            
            # Sector size (offset 0x88, 4 bytes)
            info['sector_size'] = struct.unpack('<I', data[0x88:0x8C])[0]
            
            return info
            
        except Exception as e:
            return {'error': f'Superblock parsing failed: {str(e)}'}
    
    def _find_chunk_tree(self, device):
        """Try to find chunk tree location"""
        try:
            # Implementation would involve scanning for chunk tree signatures
            # This is a complex operation that would require detailed BTRFS knowledge
            # For now, return a placeholder
            return {'status': 'search_attempted', 'found': False}
        except Exception as e:
            return {'error': str(e)}
    
    def _estimate_recovery_potential(self, device, metadata_info):
        """Estimate recovery potential based on available metadata"""
        try:
            estimate = {
                'confidence': 'unknown',
                'estimated_files': 0,
                'factors': []
            }
            
            # Check if we have basic metadata
            if 'uuid' in metadata_info:
                estimate['factors'].append('Valid UUID found')
                confidence_score = 30
            else:
                estimate['factors'].append('No valid UUID found')
                confidence_score = 10
            
            if 'total_bytes' in metadata_info and metadata_info['total_bytes'] > 0:
                estimate['factors'].append('Filesystem size detected')
                confidence_score += 20
            
            if 'node_size' in metadata_info:
                estimate['factors'].append('Node size information available')
                confidence_score += 15
            
            # Determine confidence level
            if confidence_score >= 60:
                estimate['confidence'] = 'high'
            elif confidence_score >= 30:
                estimate['confidence'] = 'medium'
            else:
                estimate['confidence'] = 'low'
            
            estimate['confidence_score'] = confidence_score
            
            return estimate
            
        except Exception as e:
            return {'error': str(e)}
    
    def _parse_size_bytes(self, size_str):
        """Parse size string to bytes"""
        try:
            size_str = size_str.strip()
            multipliers = {
                'B': 1,
                'K': 1024, 'KB': 1024, 'KiB': 1024,
                'M': 1024**2, 'MB': 1024**2, 'MiB': 1024**2,
                'G': 1024**3, 'GB': 1024**3, 'GiB': 1024**3,
                'T': 1024**4, 'TB': 1024**4, 'TiB': 1024**4
            }
            
            for suffix, multiplier in multipliers.items():
                if size_str.endswith(suffix):
                    number_part = size_str[:-len(suffix)]
                    return int(float(number_part) * multiplier)
            
            # If no suffix, assume bytes
            return int(float(size_str))
            
        except:
            return 0
    
    def _create_error_result(self, error_message):
        """Create standardized error result"""
        return {
            'success': False,
            'error': error_message,
            'method': 'error',
            'timestamp': datetime.now().isoformat()
        }
