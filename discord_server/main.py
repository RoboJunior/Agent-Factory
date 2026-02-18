import asyncio
import logging
import os

# import aiohttp
from typing import Dict, List

import discord
from aiohttp import web
from discord.ext import commands
from dotenv import load_dotenv
from ollama import AsyncClient
from opensearchpy import AsyncOpenSearch

load_dotenv()

token = os.environ.get("DISCORD_BOT_TOKEN")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL")
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST")
OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT"))
OPENSEARCH_USERNAME = os.environ.get("OPENSEARCH_USERNAME")
OPENSEARCH_PASSWORD = os.environ.get("OPENSEARCH_PASSWORD")
DISCORD_CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID"))

ollama_client = AsyncClient()

handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# Embed text
async def embed_text(query: str):
    res = await ollama_client.embeddings(model="qwen3-embedding:0.6b", prompt=query)
    return res.embedding


# Create a agent once the request is approved
# If you want durable use temporal --> Check how can we send messages to temporal
# From a centeralized place
async def store_agent_data_to_opensearch(data: Dict):
    text = " ".join(
        [data["agent_name"], data["agent_description"], data["agent_instruction"]]
    )
    vector = await embed_text(query=text)
    doc = {
        "agent_name": data["agent_name"],
        "raw": data,
        "search_text": text,
        "tools": data["tools"],
        "embedding": vector,
    }
    async with AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    ) as client:
        await client.index(
            index="agents",
            id=data["agent_name"],
            body=doc,
        )


class ApproveRejectView(discord.ui.View):
    def __init__(
        self,
        *,
        agent_name: str,
        agent_description: str,
        agent_instruction: str,
        tools: List[str],
        timeout=180,
    ):
        super().__init__(timeout=timeout)
        self.agent_name = agent_name
        self.agent_description = agent_description
        self.agent_instruction = agent_instruction
        self.tools = tools

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.message.edit(
            content=f"✅ **Approved** by {interaction.user.mention}", view=None
        )
        data = {
            "agent_name": self.agent_name,
            "agent_description": self.agent_description,
            "agent_instruction": self.agent_instruction,
            "tools": self.tools,
        }
        # Store the agent data into opensearch
        await store_agent_data_to_opensearch(data=data)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.edit(
            content=f"❌ Rejected by {interaction.user.mention}", view=None
        )


# On start event
@bot.event
async def on_ready():
    print(f"We are ready to go in, {bot.user.name}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if "shit" in message.content.lower():
        await message.delete()
        await message.channel.send(f"{message.author.mention} Dont use that word")
    # Continue handling the messages which are send to the server
    await bot.process_commands(message)


@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.mention}!")


# HTTP server code
async def handle_request(request):
    data = await request.json()
    print(data)

    try:
        agent_name = data["agent_name"]
        agent_description = data["agent_description"]
        agent_instruction = data["agent_instruction"]
        tools = data["tools"]

    except KeyError:
        return web.json_response({"error": "invalid payload"}, status=400)

    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        return web.json_response({"error": "channel not found"}, status=404)

    embed = discord.Embed(title="Agent Review Request", color=discord.Color.blue())
    embed.add_field(name="Agent Name", value=agent_name, inline=False)
    embed.add_field(name="Agent Description", value=agent_description, inline=False)
    embed.add_field(name="Agent Instruction", value=agent_instruction, inline=False)
    embed.add_field(name="Tools", value=",".join(tools), inline=False)

    view = ApproveRejectView(
        agent_name=agent_name,
        agent_description=agent_description,
        agent_instruction=agent_instruction,
        tools=tools,
    )

    # Send message asynchronously
    await channel.send(embed=embed, view=view)

    return web.json_response({"status": "sent"})


# Send agent response
async def handle_agent_request(request):
    data = await request.json()

    try:
        agent_response = data["agent_response"]
    except KeyError:
        return web.json_response({"error": "invalid payload"}, status=400)

    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        return web.json_response({"error": "channel not found"}, status=404)

    await channel.send(agent_response)
    return web.json_response({"status": "sent"})


app = web.Application()
app.router.add_post("/send_message", handle_request)
app.router.add_post("/send_agent_response", handle_agent_request)


async def start_servers():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8090)
    await site.start()
    print("Http Server running on port 8090")
    await bot.start(token=token)


# Run the bot with the logger
asyncio.run(start_servers())
