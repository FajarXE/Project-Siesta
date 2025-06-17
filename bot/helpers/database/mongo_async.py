from async_pymongo import AsyncClient
from config import Config

class MongoDB:
    """
      An Async Database
    """
    
    def __init__(self) -> None:
        self.client = AsyncClient(Config.DATABASE_URL)[Config.BOT_USERNAME]
    
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
        #
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


database = MongoDB()