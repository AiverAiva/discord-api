from fastapi import FastAPI, Request, Depends, APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import Optional
import httpx
import os

from dotenv import load_dotenv
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS"),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# print(os.getenv("CORS_ORIGINS").split(","))

DISCORD_API_URL = "https://discord.com/api/v10"
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI')
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MONGODB_URL = os.getenv("MONGODB_URL")

MANAGE_GUILD_PERMISSION = 0x20  # MANAGE_GUILD permission bit

async def get_mongo_client():
    client = AsyncIOMotorClient(MONGODB_URL)
    try:
        yield client
    finally:
        client.close()
        
@app.get('/')
def hello_world():
    return "Hello,World"

@app.get("/login") 
def login():
    return RedirectResponse(f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify+guilds")

@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        tokens = response.json()
        accessToken = tokens.get("access_token")
        return {"accessToken": accessToken}

@app.get("/user")
async def get_user(accessToken: str):
    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            f"{DISCORD_API_URL}/users/@me",
            headers={"Authorization": f"Bearer {accessToken}"}
        )
        
        user_data = user_response.json()

        guilds_response = await client.get(
            f"{DISCORD_API_URL}/users/@me/guilds",
            headers={"Authorization": f"Bearer {accessToken}"}
        )
        user_guilds = guilds_response.json()

        bot_guilds_response = await client.get(
            f"{DISCORD_API_URL}/users/@me/guilds",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
        )
        bot_guilds = bot_guilds_response.json()
        
        bot_guild_ids = {guild['id'] for guild in bot_guilds}

        for guild in user_guilds:
            guild['has_bot'] = guild['id'] in bot_guild_ids

        user_id = user_data["id"]
        avatar = user_data["avatar"]

        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png"
        user_data["avatar_url"] = avatar_url
        
        return {
            "user": user_data,
            "user_guilds": user_guilds,
        }   


class Role(BaseModel):
    id: str
    name: str
    permissions: str
    color: int

class Channel(BaseModel):
    id: str
    name: str
    type: int

class ServerDetails(BaseModel):
    id: str
    name: str
    icon: str
    owner: bool
    features: list
    roles: list[Role]
    channels: list[Channel]

class Module(BaseModel):
    id: str
    enabled: bool
    settings: dict

class Guild(BaseModel):
    guild_id: str
    modules: Optional[list] = []
    
async def get_discord_headers():
    return {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}"
    }
async def verify_user_permissions(accessToken: str, guild_id: str) -> bool:
    async with httpx.AsyncClient() as client:
        guilds_response = await client.get(
            f"{DISCORD_API_URL}/users/@me/guilds",
            headers={"Authorization": f"Bearer {accessToken}"}
        )
        user_guilds = guilds_response.json()
        try:
            user_guild = next((guild for guild in user_guilds if guild["id"] == guild_id), None)
            if user_guild is None:
                return False
            user_permissions = user_guild.get("permissions", 0)
            has_manage_guild = (int(user_permissions) & MANAGE_GUILD_PERMISSION) == MANAGE_GUILD_PERMISSION
            return has_manage_guild
        except:
            return False
        
@app.get("/server/{server_id}/roles")
async def get_server_details(server_id: str, accessToken: str, headers: dict = Depends(get_discord_headers)):
    if not await verify_user_permissions(accessToken, server_id):
        raise HTTPException(status_code=403, detail="User does not have the required permissions")

    async with httpx.AsyncClient() as client:
        roles_resp = await client.get(f"{DISCORD_API_URL}/guilds/{server_id}/roles", headers=headers)

    if roles_resp.status_code != 200:
        raise HTTPException(status_code=roles_resp.status_code, detail="Failed to fetch server details")

    roles_data = roles_resp.json()
    
    roles = [{"id": role["id"], "name": role["name"], "permissions": role["permissions"], "color": role["color"]} for role in roles_data if role["name"] != "@everyone"]
    return roles
    
@app.get("/server/{server_id}", response_model=ServerDetails)
async def get_server_details(server_id: str, accessToken: str, headers: dict = Depends(get_discord_headers)):
    if not await verify_user_permissions(accessToken, server_id):
        raise HTTPException(status_code=403, detail="User does not have the required permissions")

    async with httpx.AsyncClient() as client:
        server_resp = await client.get(f"{DISCORD_API_URL}/guilds/{server_id}", headers=headers)
        roles_resp = await client.get(f"{DISCORD_API_URL}/guilds/{server_id}/roles", headers=headers)
        channels_resp = await client.get(f"{DISCORD_API_URL}/guilds/{server_id}/channels", headers=headers)

    if server_resp.status_code != 200:
        raise HTTPException(status_code=server_resp.status_code, detail="Failed to fetch server details")

    server_data = server_resp.json()
    roles_data = roles_resp.json()
    channels_data = channels_resp.json()

    server_details = {
        "id": server_data["id"],
        "name": server_data["name"],
        "icon": server_data.get("icon"),
        "owner": server_data["owner_id"] == server_data["id"],
        "features": server_data.get("features", []),
        "roles": [{"id": role["id"], "name": role["name"], "permissions": role["permissions"], "color": role["color"]} for role in roles_data],
        "channels": [{"id": channel["id"], "name": channel["name"], "type": channel["type"]} for channel in channels_data]
    }

    return server_details

@app.get("/guild/{guild_id}", response_model=Guild)
async def get_guild(guild_id: str, accessToken: str, client: AsyncIOMotorClient = Depends(get_mongo_client)):
    if not await verify_user_permissions(accessToken, guild_id):
        raise HTTPException(status_code=403, detail="User does not have the required permissions")
    
    db = client['meow-bot']
    guilds_collection = db['guilds']
    
    guild = await guilds_collection.find_one({"guild_id": guild_id})
    
    if guild is None:
        guild = Guild(guild_id=guild_id, modules=[])
        await guilds_collection.insert_one(guild.dict())
    
    return guild

# a GET endpoint of /guild/{guild_id}/module, should return the module with the given id
@app.get("/guild/{guild_id}/module/{module_id}", response_model=Module)
async def get_guild_module(guild_id: str, module_id: str, accessToken: str, client: AsyncIOMotorClient = Depends(get_mongo_client)):
    if not await verify_user_permissions(accessToken, guild_id):
        raise HTTPException(status_code=403, detail="User does not have the required permissions")
    
    db = client['meow-bot']
    guilds_collection = db['guilds']
    
    guild = await guilds_collection.find_one({"guild_id": guild_id})
    
    if guild is None:
        raise HTTPException(status_code=404, detail="Guild not found")
    
    modules = guild.get("modules", [])
    module = next((mod for mod in modules if mod['id'] == module_id), None)
    
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")
    
    return module

# TODO: the module should be in a model but I don't know how to make it work
@app.post("/guild/{guild_id}/module", response_model=Guild)
async def update_guild_module(guild_id: str, module: dict, accessToken: str, client: AsyncIOMotorClient = Depends(get_mongo_client)):
    if not await verify_user_permissions(accessToken, guild_id):
        raise HTTPException(status_code=403, detail="User does not have the required permissions")
    
    db = client['meow-bot']
    guilds_collection = db['guilds']
    
    guild = await guilds_collection.find_one({"guild_id": guild_id})
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    modules = guild.get("modules", [])
    
    for i, mod in enumerate(modules):
        if mod['id'] == module['id']:
            modules[i] = module
            break
    else:
        modules.append(module)
    
    await guilds_collection.update_one({"guild_id": guild_id}, {"$set": {"modules": modules}})
    return Guild(guild_id=guild_id, modules=modules)

@app.post("/guild/{guild_id}/modules", response_model=Guild)
async def update_guild_modules(guild_id: str, modules: list[dict], accessToken: str, client: AsyncIOMotorClient = Depends(get_mongo_client)):
    if not await verify_user_permissions(accessToken, guild_id):
        raise HTTPException(status_code=403, detail="User does not have the required permissions")
    
    db = client['meow-bot']
    guilds_collection = db['guilds']
    
    guild = await guilds_collection.find_one({"guild_id": guild_id})
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")
    
    await guilds_collection.update_one({"guild_id": guild_id}, {"$set": {"modules": modules}})
    return Guild(guild_id=guild_id, modules=modules)

