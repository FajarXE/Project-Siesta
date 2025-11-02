import asyncio
import time
import os
from datetime import datetime, timedelta
from typing import Optional

from bot.logger import LOGGER
from bot.helpers.database.mongo_async import database


class DistributedLock:
    """
    MongoDB-based distributed lock to prevent multiple instances of the bot
    from running simultaneously with the same session.
    """
    
    def __init__(self, lock_key: str = "tg_client", ttl_minutes: int = 5):
        self.lock_key = lock_key
        self.ttl_minutes = ttl_minutes
        self.ttl_seconds = ttl_minutes * 60
        self.instance_id = self._generate_instance_id()
        self.lock_collection = None
        
    def _generate_instance_id(self) -> str:
        """Generate a unique instance identifier."""
        hostname = os.environ.get('HOSTNAME', 'unknown')
        pid = os.getpid()
        timestamp = int(time.time())
        return f"{hostname}-{pid}-{timestamp}"
    
    async def _get_collection(self):
        """Get the locks collection from MongoDB."""
        if self.lock_collection is None:
            self.lock_collection = database.db.locks
        return self.lock_collection
    
    async def acquire_lock(self) -> bool:
        """
        Try to acquire the distributed lock.
        Returns True if lock acquired successfully, False otherwise.
        """
        try:
            collection = await self._get_collection()
            
            # Create lock document
            lock_doc = {
                "_id": self.lock_key,
                "instance_id": self.instance_id,
                "acquired_at": datetime.utcnow(),
                "expires_at": datetime.utcnow() + timedelta(seconds=self.ttl_seconds),
                "hostname": os.environ.get('HOSTNAME', 'unknown'),
                "pid": os.getpid(),
                "session_name": os.environ.get('SESSION_NAME', 'siesta'),
                "session_dir": os.environ.get('SESSION_DIR', '/data/sessions')
            }
            
            # Try to insert new lock (will fail if lock exists)
            result = await collection.insert_one(lock_doc)
            
            if result.inserted_id:
                LOGGER.info(f"LOCK : Acquired distributed lock '{self.lock_key}' for instance {self.instance_id}")
                return True
                
        except Exception as e:
            # Lock might already exist, check if it's expired
            try:
                existing_lock = await collection.find_one({"_id": self.lock_key})
                if existing_lock and existing_lock.get("expires_at"):
                    if datetime.utcnow() > existing_lock["expires_at"]:
                        # Lock is expired, try to acquire it
                        result = await collection.replace_one(
                            {"_id": self.lock_key, "expires_at": existing_lock["expires_at"]},
                            lock_doc
                        )
                        if result.modified_count > 0:
                            LOGGER.info(f"LOCK : Acquired expired distributed lock '{self.lock_key}' for instance {self.instance_id}")
                            return True
                        else:
                            LOGGER.warning(f"LOCK : Failed to acquire expired lock, another instance was faster")
                            return False
                    else:
                        # Lock is still valid
                        LOGGER.warning(f"LOCK : Lock '{self.lock_key}' is held by instance {existing_lock.get('instance_id', 'unknown')}")
                        LOGGER.warning(f"LOCK : Lock expires at: {existing_lock.get('expires_at')}")
                        return False
                else:
                    LOGGER.error(f"LOCK : Unexpected error checking lock status: {e}")
                    return False
            except Exception as check_error:
                LOGGER.error(f"LOCK : Error checking lock status: {check_error}")
                return False
        
        return False
    
    async def renew_lock(self) -> bool:
        """
        Renew the lock lease to prevent expiration.
        Returns True if lock renewed successfully, False otherwise.
        """
        try:
            collection = await self._get_collection()
            
            new_expiry = datetime.utcnow() + timedelta(seconds=self.ttl_seconds)
            
            result = await collection.update_one(
                {
                    "_id": self.lock_key,
                    "instance_id": self.instance_id
                },
                {
                    "$set": {
                        "expires_at": new_expiry,
                        "renewed_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                LOGGER.debug(f"LOCK : Renewed lock '{self.lock_key}' for instance {self.instance_id}")
                return True
            else:
                LOGGER.error(f"LOCK : Failed to renew lock - instance {self.instance_id} no longer owns it")
                return False
                
        except Exception as e:
            LOGGER.error(f"LOCK : Error renewing lock: {e}")
            return False
    
    async def release_lock(self) -> bool:
        """
        Release the lock.
        Returns True if lock released successfully, False otherwise.
        """
        try:
            collection = await self._get_collection()
            
            result = await collection.delete_one({
                "_id": self.lock_key,
                "instance_id": self.instance_id
            })
            
            if result.deleted_count > 0:
                LOGGER.info(f"LOCK : Released distributed lock '{self.lock_key}' for instance {self.instance_id}")
                return True
            else:
                LOGGER.warning(f"LOCK : Lock '{self.lock_key}' was not held by instance {self.instance_id}")
                return False
                
        except Exception as e:
            LOGGER.error(f"LOCK : Error releasing lock: {e}")
            return False
    
    async def start_renewal_task(self):
        """Start a background task to periodically renew the lock."""
        async def renewal_loop():
            while True:
                try:
                    await asyncio.sleep(self.ttl_seconds // 2)  # Renew at half the TTL
                    success = await self.renew_lock()
                    if not success:
                        LOGGER.error("LOCK : Failed to renew lock, stopping renewal task")
                        break
                except asyncio.CancelledError:
                    LOGGER.info("LOCK : Renewal task cancelled")
                    break
                except Exception as e:
                    LOGGER.error(f"LOCK : Error in renewal loop: {e}")
                    await asyncio.sleep(10)  # Wait before retrying
        
        return asyncio.create_task(renewal_loop())