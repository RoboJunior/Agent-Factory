import os
import uuid
from typing import Dict

from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import types
from ollama import AsyncClient
from opensearchpy import AsyncOpenSearch

from mcp_server.config.settings import get_settings
from mcp_server.schema.agent_message import AgentMessage
from mcp_server.service.discord_service import send_agent_message

ollama_client = AsyncClient()


# Text Embedding function
async def embed_text(query: str):
    res = await ollama_client.embeddings(model="qwen3-embedding:0.6b", prompt=query)
    return res.embedding


# Search agents based on name and description
async def search_relevant_agents(agent_name: str, agent_description: str):
    text = f"{agent_name} {agent_description}"

    query_vector = await embed_text(query=text)

    async with AsyncOpenSearch(
        hosts=[
            {
                "host": get_settings().OPENSEARCH_HOST,
                "port": get_settings().OPENSEARCH_PORT,
            }
        ],
        http_auth=(
            get_settings().OPENSEARCH_USERNAME,
            get_settings().OPENSEARCH_PASSWORD,
        ),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    ) as client:
        body = {
            "size": 3,
            "query": {
                "hybrid": {
                    "queries": [
                        {
                            "multi_match": {
                                "query": text,
                                "fields": ["agent_name^3", "search_text"],
                            }
                        },
                        {"knn": {"embedding": {"vector": query_vector, "k": 3}}},
                    ]
                }
            },
        }
        res = await client.search(
            index="agents", body=body, params={"search_pipeline": "agent_team_rrf"}
        )
        return [hit["_source"]["raw"] for hit in res["hits"]["hits"]]


# Agent Executor
class AgentExecutor:
    def __init__(self, app_name, session_service: InMemorySessionService, agent: Agent):
        self.app_name = app_name
        self.session_service = session_service
        self.agent = agent

    async def execute(self, message: AgentMessage):
        session_id = message.session_id
        user_id = message.user_id

        # CREATE OR RETRIEVE SESSION
        session = await self.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )

        if not session:
            session = await self.session_service.create_session(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )

        # CREATE RUNNER USING THE SAME SESSION SERVICE
        runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )

        # RUN THE AGENT
        content = types.Content(role="user", parts=[types.Part(text=message.query)])
        events = runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        )

        # agent_response = {}
        async for event in events:
            # If u want to capture everything do it accordingly
            if event.is_final_response():
                return event.content.parts[0].text

        # return agent_response


# Run the remote agent
async def run_remote_agent(
    remote_agent: Agent, session_id: str, user_id: str, query: str
):
    session_service = InMemorySessionService()
    agent_runner = AgentExecutor(
        app_name="remote_agents", session_service=session_service, agent=remote_agent
    )
    response = await agent_runner.execute(
        message=AgentMessage(session_id=session_id, user_id=user_id, query=query)
    )
    return response


# Response is pushed to discord for now
async def invoke_remote_agent(payload: Dict):
    # inializing all the env variable to env
    os.environ["GOOGLE_API_KEY"] = get_settings().GOOGLE_API_KEY
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = get_settings().GOOGLE_GENAI_USE_VERTEXAI

    # Initalizing the toolset for the agent to access
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=get_settings().MCP_SERVER_URL
        ),
        tool_filter=payload["required_tools"],
    )

    # Initalizing the agent itself to run the query
    remote_agent = Agent(
        model="gemini-2.5-flash",
        name=payload["agent_name"].replace(" ", "_"),
        description=payload["agent_description"],
        instruction=payload["agent_instruction"],
        tools=[toolset],
    )
    # Run the agent query
    response = await run_remote_agent(
        remote_agent=remote_agent,
        session_id=uuid.uuid4().hex,
        user_id=uuid.uuid4().hex,
        query=payload["input_query"],
    )
    await send_agent_message(agent_response=response)
    return "Process Done"
