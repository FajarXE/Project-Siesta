#!/usr/bin/env python3
"""
Configuration validation script for MongoDB settings.
This script validates the MongoDB configuration and helps diagnose issues.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from config import Config
    print("✅ Configuration loaded successfully")
    print(f"✅ MONGODB_URI: {Config.MONGODB_URI}")
    print(f"✅ MONGODB_DB: {Config.MONGODB_DB}")
    
    # Test MongoDB connection (optional, requires actual MongoDB)
    try:
        from async_pymongo import AsyncClient
        import asyncio
        
        async def test_connection():
            try:
                client = AsyncClient(Config.MONGODB_URI)
                # Test server info
                server_info = await client.server_info()
                print(f"✅ MongoDB connection successful: {server_info.get('version', 'unknown version')}")
                
                # Test database access
                db = client[Config.MONGODB_DB]
                # Test a simple operation
                await db.command('ping')
                print(f"✅ Database '{Config.MONGODB_DB}' accessible")
                
                await client.close()
                return True
            except Exception as e:
                print(f"❌ MongoDB connection failed: {e}")
                return False
        
        # Run the async test
        result = asyncio.run(test_connection())
        if result:
            print("✅ All MongoDB tests passed")
        else:
            print("❌ MongoDB tests failed")
            sys.exit(1)
            
    except ImportError:
        print("⚠️  async_pymongo not available, skipping connection test")
    except Exception as e:
        print(f"❌ Error during MongoDB test: {e}")
        sys.exit(1)
        
except Exception as e:
    print(f"❌ Configuration error: {e}")
    print("\nPlease check your .env file:")
    print("- MONGODB_URI should be like: mongodb://localhost:27017/")
    print("- MONGODB_DB should be a simple name like: siesta_bot")
    print("- Database names cannot contain '/', '\\', ' ', or start with '.'")
    sys.exit(1)

print("\n🎉 Configuration validation complete!")