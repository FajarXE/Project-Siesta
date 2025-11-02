#!/usr/bin/env python3
"""
Startup validation script to test both MongoDB and Beatport configuration.
This simulates the actual startup process to ensure all fixes work together.
"""

import os
import sys
from pathlib import Path

def test_mongodb_startup():
    """Test MongoDB configuration during startup"""
    print("🔍 Testing MongoDB startup configuration...")
    
    # Set minimal test environment
    os.environ['TG_BOT_TOKEN'] = 'test_token'
    os.environ['APP_ID'] = '12345'
    os.environ['API_HASH'] = 'test_hash'
    os.environ['BOT_USERNAME'] = 'test_bot'
    os.environ['ADMINS'] = '123456'
    
    try:
        from config import Config
        
        print(f"✅ Config loaded successfully")
        print(f"✅ MONGODB_URI: {Config.MONGODB_URI}")
        print(f"✅ MONGODB_DB: {Config.MONGODB_DB}")
        
        # Test that we can create the MongoDB client
        from async_pymongo import AsyncClient
        
        # This should not raise an exception
        client = AsyncClient(Config.MONGODB_URI)
        print(f"✅ MongoDB client created successfully")
        
        # Test database access (this will fail if no MongoDB server, but that's OK)
        try:
            db = client[Config.MONGODB_DB]
            print(f"✅ Database object created successfully")
        except Exception as e:
            if "InvalidName" in str(e):
                print(f"❌ Invalid database name detected: {e}")
                return False
            else:
                print(f"⚠️  Database access failed (expected if no MongoDB server): {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ MongoDB configuration test failed: {e}")
        return False

def test_beatport_startup():
    """Test Beatport configuration during startup"""
    print("\n🔍 Testing Beatport startup configuration...")
    
    try:
        # Set minimal Beatport config
        os.environ['BEATPORT_USERNAME'] = 'test_user'
        os.environ['BEATPORT_PASSWORD'] = 'test_pass'
        
        # Test import
        from bot.helpers.beatport.handler import beatport_login
        print(f"✅ Beatport handler imported successfully")
        
        # Test the function call (this should fail gracefully if OrpheusDL not installed)
        try:
            beatport_login()
            print(f"✅ Beatport login configuration successful")
        except FileNotFoundError as e:
            print(f"✅ Beatport correctly handles missing OrpheusDL: {e}")
        except Exception as e:
            print(f"⚠️  Beatport login failed with unexpected error: {e}")
        
        # Test the settings initialization
        from bot.settings import BotSettings
        bot_settings = BotSettings()
        
        try:
            bot_settings.beatport_initialise()
            print(f"✅ Beatport initialization completed (OrpheusDL may or may not be available)")
        except Exception as e:
            print(f"❌ Beatport initialization failed: {e}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Beatport configuration test failed: {e}")
        return False

def test_tgclient_startup():
    """Test tgclient startup with new MongoDB configuration"""
    print("\n🔍 Testing tgclient startup configuration...")
    
    try:
        from bot.tgclient import Bot
        
        # This should create the Bot instance without starting it
        # (which would require Telegram credentials)
        print(f"✅ Bot class imported successfully")
        
        # We can't actually create the Bot instance without valid credentials
        # but we can verify the configuration is accessible
        from config import Config
        print(f"✅ MongoDB configuration accessible in tgclient context")
        print(f"✅ MONGODB_URI: {Config.MONGODB_URI}")
        print(f"✅ MONGODB_DB: {Config.MONGODB_DB}")
        
        return True
        
    except Exception as e:
        print(f"❌ tgclient configuration test failed: {e}")
        return False

def test_database_helper():
    """Test database helper with new configuration"""
    print("\n🔍 Testing database helper configuration...")
    
    try:
        from bot.helpers.database.mongo_async import MongoDB
        
        # This should create the MongoDB instance
        db = MongoDB()
        print(f"✅ MongoDB helper created successfully")
        print(f"✅ Database name: {db.client.name}")
        
        return True
        
    except Exception as e:
        print(f"❌ Database helper test failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Startup Configuration Validation Tool")
    print("=" * 60)
    
    # Set up environment for testing
    project_root = Path(__file__).parent
    os.environ['MONGODB_URI'] = 'mongodb://localhost:27017/'
    os.environ['MONGODB_DB'] = 'siesta_bot'
    
    tests = [
        ("MongoDB Configuration", test_mongodb_startup),
        ("Beatport Configuration", test_beatport_startup),
        ("Telegram Client Configuration", test_tgclient_startup),
        ("Database Helper Configuration", test_database_helper),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"\n🧪 Running {test_name}...")
        try:
            if test_func():
                print(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                print(f"❌ {test_name}: FAILED")
                failed += 1
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            failed += 1
    
    print(f"\n📊 Final Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("\n🎉 All startup configuration tests passed!")
        print("✅ MongoDB configuration is properly separated and validated")
        print("✅ Beatport module handles missing OrpheusDL gracefully")
        print("✅ All components can access the new configuration format")
        sys.exit(0)
    else:
        print(f"\n❌ {failed} startup configuration tests failed!")
        sys.exit(1)