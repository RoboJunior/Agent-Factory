from typing import List

import aiohttp


# Send the agent details to discord for approval
async def send_message(
    agent_name: str, agent_description: str, agent_instruction: str, tools: List[str]
):
    data = {
        "agent_name": agent_name,
        "agent_description": agent_description,
        "agent_instruction": agent_instruction,
        "tools": tools,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url="http://localhost:8090/send_message", json=data
        ) as response:
            return await response.json()


# Either this can be published to a centerlized system like redis and the
# The list of subscribers listening to that event gets that and can consume it
# Send the agent message to the discord
async def send_agent_message(agent_response: str):
    data = {
        "agent_response": agent_response,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url="http://localhost:8090/send_agent_response", json=data
        ) as response:
            return await response.json()
