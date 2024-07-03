from fastapi import FastAPI, Request, Depends, APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import os

from dotenv import load_dotenv
load_dotenv()

app = FastAPI()
# router = APIRouter(prefix="/api")

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
        # Get user info
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
        # print(user_guilds)

        bot_guilds_response = await client.get(
            f"{DISCORD_API_URL}/users/@me/guilds",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
        )
        bot_guilds = bot_guilds_response.json()
        
        bot_guild_ids = {guild['id'] for guild in bot_guilds}

        # Mark guilds where the bot is present
        for guild in user_guilds:
            guild['has_bot'] = guild['id'] in bot_guild_ids
            # print(guild)


        user_id = user_data["id"]
        avatar = user_data["avatar"]

        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png"
        user_data["avatar_url"] = avatar_url
        # bot_guild_ids = {guild['id'] for guild in bot_guilds}
        # bot_guilds_data = [guild for guild in bot_guilds if guild['id'] in bot_guild_ids]
 
        # user_guilds_with_bot = [guild for guild in user_guilds if guild['id'] in bot_guild_ids]
        # for guild in user_guilds:
        #     guild['has_bot'] = guild['id'] in bot_guild_ids
 
        # return user_data
        # print(user_guilds)
        return {
            "user": user_data,
            "user_guilds": user_guilds,
            # "bot_guilds": bot_guilds_data,
            # "user_guilds_with_bot": user_guilds_with_bot
        }   

# app.include_router(router)

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

async def get_discord_headers():
    return {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}"
    }

@app.get("/server/{server_id}", response_model=ServerDetails)
async def get_server_details(server_id: str, headers: dict = Depends(get_discord_headers)):
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