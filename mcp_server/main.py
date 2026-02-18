import asyncio
from typing import List

from dotenv import load_dotenv
from fastmcp import FastMCP

from mcp_server.service.agent_service import (
    invoke_remote_agent,
    search_relevant_agents,
)
from mcp_server.service.discord_service import send_message
from mcp_server.service.invoice_service import extract_invoice_details
from mcp_server.service.tool_service import search_relevent_tools

# Agent Server
agent_server = FastMCP(
    name="Agent Manager",
    instructions="""This server has capablities to manage agents""",
)


# Search relevant agents
@agent_server.tool(
    name="search_agent",
    description="This tool is used to search agents",
    tags=["agent"],
)
async def search_agent(agent_name: str, agent_description: str):
    response = await search_relevant_agents(
        agent_name=agent_name, agent_description=agent_description
    )
    return response


# Tool which is used to create a agent with human approval
@agent_server.tool(
    name="create_agent",
    description="This tool is used to create a new agent",
    tags=["agent"],
)
async def create_agent(
    agent_name: str, agent_description: str, agent_insturctions: str, tools: List[str]
):
    response = await send_message(
        agent_name=agent_name,
        agent_description=agent_description,
        agent_instruction=agent_insturctions,
        tools=tools,
    )
    return response


# Search tools similar tools
@agent_server.tool(
    name="tool_search",
    description="This tool is used to search similar tools which can be attached to the agents",
    tags=["tool"],
)
async def tool_search(tool_name: str, tool_description: str):
    response = await search_relevent_tools(
        tool_name=tool_name, tool_description=tool_description
    )
    return response


# Only add temporal if u need durability
@agent_server.tool(
    name="call_agent",
    description="This tool is used to invoke the agent with the required parameters",
)
async def call_agent(
    agent_name: str,
    agent_description: str,
    agent_instruction: str,
    required_tools: List[str],
    input_query: str,
):
    payload = {
        "agent_name": agent_name,
        "agent_description": agent_description,
        "agent_instruction": agent_instruction,
        "required_tools": required_tools,
        "input_query": input_query,
    }
    asyncio.create_task(invoke_remote_agent(payload=payload))
    return {"Message": f"{agent_name} started running.."}


# Invoice Extraction
@agent_server.tool(
    name="invoice_extraction",
    description="This tool is used to extract the details from a given invoice",
    tags=["invoice"],
)
async def invoice_extraction(invoice_image_path: str):
    response = await extract_invoice_details(image_path=invoice_image_path)
    return response


# Run the mcp server
if __name__ == "__main__":
    agent_server.run(transport="http", host="0.0.0.0", port=8005)
