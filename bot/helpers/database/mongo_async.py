from async_pymongo import AsyncClient
from config import Config

import logging, traceback

class MongoDB:
    """
      An Async Database
    """
    
    def __init__(self) -> None:
        self.db = AsyncClient(Config.MONGODB_URI)
        self.client = self.db[Config.MONGODB_DB]
    
    async def initialize_users(self) -> dict:
        exists = await self.client.users.find_one({})
        if exists:
            user_data = {} 
            rows = self.client.users.find({})
            # Return User data
            async for row in rows:
                uid = row["_id"]
                del row["_id"]
                user_data[uid] = row
            return user_data
        return {}
    
    async def authorize_chats(self, user_id: int, remove=False) -> bool:
        if remove:
            ret = await self.client.music.update_one({"_id": Config.BOT_USERNAME}, {"pull": {"AUTH_CHATS": user_id}}, upsert=True)
            return bool(ret)
        
        ret = await self.client.music.update_one({"_id": Config.BOT_USERNAME}, {"$addToSet": {"AUTH_CHATS": user_id}}, upsert=True)
        
        return bool(ret)
    
    async def authorize_users(self, user_id: int, remove=False) -> bool:
        if remove:
            ret = await self.client.music.update_one({"_id": Config.BOT_USERNAME}, {"pull": {"AUTH_USERS": user_id}}, upsert=True)
            return bool(ret)
        
        ret = await self.client.music.update_one({"_id": Config.BOT_USERNAME}, {"$addToSet": {"AUTH_USERS": user_id}}, upsert=True)
        
        return bool(ret)
    
    async def set_variable(self, key: str, value: str|bool|int|None) -> bool:
        ret = await self.client.music.update_one({"_id": Config.BOT_USERNAME}, {"$set": {key: value}}, upsert=True)
        return bool(ret)
    
    async def get_variable(self, query: None|dict = None) -> dict:
        if not query:
            query = {}
        data_list = [i async for i in self.client.music.find(query)]
        data_dict = {}
        
        for data in data_list:
            data_dict = data
        if "_id" in data_dict:
            data_dict.pop("_id")
        return data_dict

    async def save_user_settings(self, user_id: int=0, data: dict={}) -> None:
        user_id = int(user_id) if isinstance(user_id, str) else user_id
        try:
            await self.client.users.update_one({"_id": user_id}, {"$set": data}, upsert=True)
        except Exception:
            logging.info(traceback.format_exc())

database = MongoDB()