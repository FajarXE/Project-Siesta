#!/usr/bin/env python3
"""
MongoDB configuration validation script.
This script validates only the MongoDB configuration settings.
"""

import os
import sys
from pathlib import Path

def validate_database_name(db_name: str) -> bool:
    """Validate MongoDB database name according to MongoDB rules"""
    if not db_name:
        return False
    
    # Database names cannot contain: '/', '\', ' ', '.', '"', '*', '<', '>', ':', '|', '?'
    invalid_chars = ['/', '\\', ' ', '.', '"', '*', '<', '>', ':', '|', '?']
    
    for char in invalid_chars:
        if char in db_name:
            return False
    
    # Cannot be empty string
    if not db_name.strip():
        return False
    
    # Cannot be null
    if db_name.lower() == 'null':
        return False
    
    return True

def test_mongodb_config():
    """Test MongoDB configuration parsing"""
    print("🔍 Testing MongoDB configuration parsing...")
    
    # Test cases
    test_cases = [
        # (uri, db, should_pass, description)
        ("mongodb://localhost:27017/", "siesta_bot", True, "Valid config"),
        ("mongodb://user:pass@localhost:27017/", "test_db", True, "Valid config with auth"),
        ("mongodb://localhost:27017", "mydb", True, "Valid config without trailing slash"),
        ("mongodb://localhost:27017/project/siesta", "db", False, "URI contains database path"),
        ("mongodb://localhost:27017/", "bad/name", False, "Database name with slash"),
        ("mongodb://localhost:27017/", "bad name", False, "Database name with space"),
        ("mongodb://localhost:27017/", ".hidden", False, "Database name starting with dot"),
        ("mongodb://localhost:27017/", "test.db", False, "Database name with dot"),
    ]
    
    passed = 0
    failed = 0
    
    for uri, db, should_pass, description in test_cases:
        try:
            # Validate database name
            db_valid = validate_database_name(db)
            
            # Check if URI contains database path (invalid)
            uri_has_db = False
            if '/' in uri.rsplit(':', 1)[-1] and not uri.endswith('/'):
                uri_has_db = True
            
            # Overall validation
            is_valid = db_valid and not uri_has_db
            
            if is_valid == should_pass:
                print(f"✅ {description}: PASS")
                passed += 1
            else:
                print(f"❌ {description}: FAIL")
                if should_pass:
                    print(f"   Expected to pass but failed. URI: {uri}, DB: {db}")
                    if not db_valid:
                        print(f"   Database name validation failed")
                    if uri_has_db:
                        print(f"   URI contains database path")
                else:
                    print(f"   Expected to fail but passed")
                failed += 1
                
        except Exception as e:
            print(f"❌ {description}: ERROR - {e}")
            failed += 1
    
    print(f"\n📊 Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All MongoDB configuration tests passed!")
        return True
    else:
        print("❌ Some tests failed")
        return False

def test_legacy_parsing():
    """Test legacy DATABASE_URL parsing"""
    print("\n🔍 Testing legacy DATABASE_URL parsing...")
    
    test_cases = [
        ("mongodb://localhost:27017/projectsiesta", "mongodb://localhost:27017/", "projectsiesta", True),
        ("mongodb://user:pass@host:27017/mydb", "mongodb://user:pass@host:27017/", "mydb", True),
        ("mongodb://localhost:27017/", "", "", False),  # No database to extract
        ("mongodb://localhost:27017", "", "", False),  # No database to extract
    ]
    
    passed = 0
    failed = 0
    
    for db_url, expected_uri, expected_db, should_work in test_cases:
        try:
            # Simulate the parsing logic from config.py
            if '/' in db_url.rsplit(':', 1)[-1]:
                parts = db_url.rsplit('/', 1)
                parsed_uri = parts[0] + '/'
                parsed_db = parts[1]
            else:
                parsed_uri = db_url
                parsed_db = ""
            
            if should_work:
                if parsed_uri == expected_uri and parsed_db == expected_db:
                    print(f"✅ Legacy parsing: {db_url} -> URI: {parsed_uri}, DB: {parsed_db}")
                    passed += 1
                else:
                    print(f"❌ Legacy parsing failed: {db_url}")
                    print(f"   Expected URI: {expected_uri}, DB: {expected_db}")
                    print(f"   Got URI: {parsed_uri}, DB: {parsed_db}")
                    failed += 1
            else:
                # This should not work as expected
                if parsed_db == "":
                    print(f"✅ Legacy correctly rejects: {db_url}")
                    passed += 1
                else:
                    print(f"❌ Legacy should reject but parsed: {db_url}")
                    failed += 1
                    
        except Exception as e:
            print(f"❌ Legacy parsing error: {e}")
            failed += 1
    
    print(f"\n📊 Legacy parsing results: {passed} passed, {failed} failed")
    return failed == 0

if __name__ == "__main__":
    print("🚀 MongoDB Configuration Validation Tool")
    print("=" * 50)
    
    config_ok = test_mongodb_config()
    legacy_ok = test_legacy_parsing()
    
    if config_ok and legacy_ok:
        print("\n🎉 All validation tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some validation tests failed!")
        sys.exit(1)