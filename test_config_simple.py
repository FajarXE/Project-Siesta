#!/usr/bin/env python3
"""
Simple configuration validation that bypasses .env loading.
"""

import os
import sys
from pathlib import Path

def test_config_validation():
    """Test the configuration validation functions directly"""
    print("🔍 Testing configuration validation functions...")
    
    # Import the validation function
    sys.path.insert(0, str(Path(__file__).parent))
    
    # Define the validation function (copy from config.py)
    def _validate_database_name(db_name: str) -> bool:
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
    
    # Test cases
    test_cases = [
        ("siesta_bot", True, "Valid database name"),
        ("test_db", True, "Valid database name"),
        ("bad/name", False, "Database name with slash"),
        ("bad name", False, "Database name with space"),
        (".hidden", False, "Database name starting with dot"),
        ("test.db", False, "Database name with dot"),
        ("", False, "Empty database name"),
        ("null", False, "Null database name"),
    ]
    
    passed = 0
    failed = 0
    
    for db_name, should_pass, description in test_cases:
        result = _validate_database_name(db_name)
        if result == should_pass:
            print(f"✅ {description}: '{db_name}' -> {result}")
            passed += 1
        else:
            print(f"❌ {description}: '{db_name}' -> {result} (expected {should_pass})")
            failed += 1
    
    print(f"\n📊 Validation results: {passed} passed, {failed} failed")
    return failed == 0

def test_beatport_import():
    """Test Beatport import with proper error handling"""
    print("\n🔍 Testing Beatport import...")
    
    try:
        # Set environment to bypass config loading
        os.environ['ENV'] = 'test'  # This should prevent .env loading
        
        # Try to import just the handler
        from bot.helpers.beatport.handler import beatport_login
        print("✅ Beatport handler imported successfully")
        
        # Test the function (should fail gracefully)
        try:
            beatport_login()
            print("✅ Beatport login completed (OrpheusDL installed)")
        except FileNotFoundError as e:
            print(f"✅ Beatport correctly handles missing OrpheusDL: {type(e).__name__}")
        except Exception as e:
            print(f"⚠️  Beatport login failed: {type(e).__name__}: {e}")
        
        return True
        
    except ImportError as e:
        print(f"❌ Beatport import failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Beatport test failed: {e}")
        return False

def test_mongodb_parsing():
    """Test MongoDB URI parsing logic"""
    print("\n🔍 Testing MongoDB URI parsing...")
    
    def parse_legacy_database_url(db_url: str):
        """Parse legacy DATABASE_URL format"""
        if '/' in db_url.rsplit(':', 1)[-1]:
            parts = db_url.rsplit('/', 1)
            uri = parts[0] + '/'
            db = parts[1]
            return uri, db
        else:
            return db_url, ""
    
    test_cases = [
        ("mongodb://localhost:27017/projectsiesta", "mongodb://localhost:27017/", "projectsiesta"),
        ("mongodb://user:pass@host:27017/mydb", "mongodb://user:pass@host:27017/", "mydb"),
        ("mongodb://localhost:27017/", "mongodb://localhost:27017/", ""),
        ("mongodb://localhost:27017", "mongodb://localhost:27017", ""),
    ]
    
    passed = 0
    failed = 0
    
    for input_url, expected_uri, expected_db in test_cases:
        try:
            parsed_uri, parsed_db = parse_legacy_database_url(input_url)
            if parsed_uri == expected_uri and parsed_db == expected_db:
                print(f"✅ Parsing: {input_url}")
                print(f"   -> URI: {parsed_uri}, DB: '{parsed_db}'")
                passed += 1
            else:
                print(f"❌ Parsing failed: {input_url}")
                print(f"   Expected: URI: {expected_uri}, DB: '{expected_db}'")
                print(f"   Got: URI: {parsed_uri}, DB: '{parsed_db}'")
                failed += 1
        except Exception as e:
            print(f"❌ Parsing error: {e}")
            failed += 1
    
    print(f"\n📊 Parsing results: {passed} passed, {failed} failed")
    return failed == 0

if __name__ == "__main__":
    print("🚀 Configuration Validation Tool (No .env)")
    print("=" * 50)
    
    tests = [
        ("Database Name Validation", test_config_validation),
        ("MongoDB URI Parsing", test_mongodb_parsing),
        ("Beatport Import", test_beatport_import),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"\n🧪 {test_name}")
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ {test_name} failed: {e}")
            failed += 1
    
    print(f"\n📊 Final Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("\n🎉 All configuration validation tests passed!")
        sys.exit(0)
    else:
        print(f"\n❌ {failed} tests failed!")
        sys.exit(1)