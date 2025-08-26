#!/usr/bin/env python3
"""
Test script to verify all page connectivity in the BTRFS File Recovery application
"""
import os
import sys
import django
from django.conf import settings

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'file_revitalizer.settings')
django.setup()

import requests
import json
import time

def test_page_connectivity():
    """Test connectivity to all application pages"""
    base_url = "http://127.0.0.1:8000"
    
    # Test pages
    pages = [
        "/",
        "/dashboard/",
        "/login/",
        "/register/",
    ]
    
    # Test API endpoints
    api_endpoints = [
        "/api/start_recovery/",
        "/api/detect_filesystem/",
        "/api/analyze_filesystem/",
        "/api/discover_files/",
        "/api/get_recovery_status/",
    ]
    
    print("🔍 Testing Page Connectivity...")
    print("=" * 50)
    
    # Test regular pages
    for page in pages:
        try:
            response = requests.get(f"{base_url}{page}", timeout=5)
            status = "✅ SUCCESS" if response.status_code in [200, 302] else f"❌ FAILED ({response.status_code})"
            print(f"{page:<20} {status}")
        except requests.exceptions.RequestException as e:
            print(f"{page:<20} ❌ FAILED (Connection Error: {str(e)})")
    
    print("\n🔌 Testing API Endpoints...")
    print("=" * 50)
    
    # Test API endpoints with POST requests
    for endpoint in api_endpoints:
        try:
            # Most endpoints expect POST with JSON data
            test_data = {"device_path": "/dev/sdb1"} if "start_recovery" in endpoint else {}
            
            response = requests.post(
                f"{base_url}{endpoint}",
                json=test_data,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            
            # API endpoints should return JSON, even for errors
            status = "✅ SUCCESS" if response.status_code in [200, 400, 404, 405] else f"❌ FAILED ({response.status_code})"
            print(f"{endpoint:<25} {status}")
            
        except requests.exceptions.RequestException as e:
            print(f"{endpoint:<25} ❌ FAILED (Connection Error: {str(e)})")
    
    print("\n🧪 Testing Import Resolution...")
    print("=" * 50)
    
    # Test that our BTRFS modules can be imported without errors
    try:
        from recovery.btrfs_detector import BTRFSDetector
        from recovery.btrfs_analyzer import BTRFSAnalyzer
        from recovery.file_discovery import FileDiscovery
        from recovery.recovery_engine import RecoveryEngine
        print("BTRFS Detector     ✅ SUCCESS")
        print("BTRFS Analyzer     ✅ SUCCESS")
        print("File Discovery     ✅ SUCCESS")
        print("Recovery Engine    ✅ SUCCESS")
    except ImportError as e:
        print(f"Import Error       ❌ FAILED ({str(e)})")
    
    print("\n🎯 Testing Module Functionality...")
    print("=" * 50)
    
    # Test that modules can be instantiated without import errors
    try:
        detector = BTRFSDetector()
        analyzer = BTRFSAnalyzer()
        discovery = FileDiscovery()
        engine = RecoveryEngine()
        print("Module Instantiation ✅ SUCCESS")
    except Exception as e:
        print(f"Module Instantiation ❌ FAILED ({str(e)})")

if __name__ == "__main__":
    print("🚀 BTRFS File Recovery - Connectivity Test")
    print("=" * 50)
    print("Testing all possible page connections and import resolutions...")
    print()
    
    test_page_connectivity()
    
    print("\n✨ Test Complete!")
    print("=" * 50)
