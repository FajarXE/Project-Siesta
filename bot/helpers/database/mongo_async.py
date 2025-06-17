from async_pymongo import AsyncClient
from config import Config
from attrify import Attrify

class MongoDB:
    """
      An Async Database
    """
    
    def __init__(self) -> None:
        self.client = AsyncClient(Config.DATABASE_URL)[Config.BOT_USERNAME]
    
    async def authorize_chat(self, user_id: int) -> bool:
        exists = await self.client.music.find_one({"_id": Config.BOT_USERNAME, "AUTH_CHATS": user_id})
        if exists:
            return False
        ret = await self.client.music.update_one({"_id": Config.BOT_USERNAME}, {"$addToSet": {"AUTH_CHATS": user_id}}, upsert=True)
        await self.client.close()
        return bool(ret)
    
    async def authorize_users(self, user_id: int) -> bool:
        exists = await self.client.music.find_one({"_id": Config.BOT_USERNAME, "AUTH_USERS": user_id})
        if exists:
            return False
        ret = await self.client.music.update_one({"_id": Config.BOT_USERNAME}, {"$addToSet": {"AUTH_USERS": user_id}}, upsert=True)
        await self.client.close()
        return bool(ret)
    
    async def set_variable(self, key: str, value: str|bool|int) -> bool:
        ret = await self.client.music.update_one({"_id": Config.BOT_USERNAME}, {"$set": {key: value}})
        await self.client.close()
        return bool(ret)
    
    async def get_variable(self, query: None|dict) -> dict:
        if not query:
            query = {}
        data_list = [i async for i in self.client.music.find(query)
        data_dict = {}
        
        for data in data_list:
            data_dict = data
        
        await self.client.close()
        if "_id" in data_dict:
            data_dict.pop("_id")
        return data_dict


database = MongoDB()