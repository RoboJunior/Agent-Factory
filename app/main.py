# import asyncio
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.llm_agent import Agent

# from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import types
from opensearchpy import AsyncOpenSearch

from app.schema.agent_message import AgentMessage

load_dotenv()

app = FastAPI(title="Agent Factory")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Loading all the .env variable
os.environ["GOOGLE_API_KEY"] = os.environ.get("GOOGLE_API_KEY")
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL")
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST")
OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT"))
OPENSEARCH_USERNAME = os.environ.get("OPENSEARCH_USERNAME")
OPENSEARCH_PASSWORD = os.environ.get("OPENSEARCH_PASSWORD")


# Initalizing the agent manager
toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=MCP_SERVER_URL),
    tool_filter=["create_agent", "tool_search", "search_agent", "call_agent"],
)
session_service = InMemorySessionService()


# Orchestrator agent
root_agent = Agent(
    model="gemini-2.5-flash",
    name="orchestrator_agent",
    description="Agent who is responsible for creating and managing all the agents",
    instruction="""
            Execution Flow
                Search for a suitable existing agent.
                If found → invoke the agent with required parameters.
                If not found → search for required tools.
                If any required tools are missing → return a tool creation request.
            Create a new agent only if:
                No suitable agent exists, and
                All required tools are available.
                Do not create agents for tasks that can be handled directly.
                Never invoke unavailable agents.
            Output Rules
                Return only the final decision and action taken.
                No reasoning, explanations, or extra text.
                Response must be concise, deterministic, and unambiguous.""",
    tools=[toolset],
    generate_content_config=types.GenerateContentConfig(temperature=0.0),
)


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

        agent_response = {}
        async for event in events:
            if event.get_function_calls():
                agent_response["function_calls"] = event.get_function_calls()
            elif event.get_function_responses():
                agent_response["function_responses"] = event.get_function_responses()
            elif event.is_final_response():
                agent_response["final_response"] = event.content.parts[0].text

        return agent_response


async def run_remote_agent(
    remote_agent: Agent, session_id: str, user_id: str, query: str
):
    agent_runner = AgentExecutor(
        app_name="remote_agents", session_service=session_service, agent=remote_agent
    )
    response = await agent_runner.execute(
        message=AgentMessage(session_id=session_id, user_id=user_id, query=query)
    )
    return response


# Chat Route
@app.post("/invoke_agent")
async def invoke_agent(session_id: str, user_id: str, query: str):
    return await run_remote_agent(
        remote_agent=root_agent, session_id=session_id, user_id=user_id, query=query
    )


# Get all agents available
@app.get("/get_all_agents")
async def get_all_remote_agents():
    async with AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    ) as client:
        index_exists = await client.indices.exists(index="agents")
        if not index_exists:
            return []

        # Search all documents
        res = await client.search(
            index="agents",
            body={"query": {"match_all": {}}},
            size=1000,
        )

        # Extract only the raw from the docs
        hits = res["hits"]["hits"]
        return [hit["_source"]["raw"] for hit in hits]


@app.get("/get_all_tools")
async def get_all_remote_tools():
    async with AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    ) as client:
        index_exists = await client.indices.exists(index="agents")
        if not index_exists:
            return []

        # Search all documents
        res = await client.search(
            index="tools",
            body={"query": {"match_all": {}}},
            size=1000,
        )

        # Extract only the raw from the docs
        hits = res["hits"]["hits"]
        return [hit["_source"]["raw"] for hit in hits]


@app.delete("/delete_agent/{name}")
async def delete_agent(name: str):
    async with AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    ) as client:
        res = await client.search(
            index="agents", body={"query": {"term": {"raw.agent_name.keyword": name}}}
        )

        hits = res["hits"]["hits"]
        if not hits:
            raise HTTPException(status_code=404, detail="Agent not found")

        deleted_docs = []
        for hit in hits:
            doc_id = hit["_id"]
            response = await client.delete(index="agents", id=doc_id)
            deleted_docs.append({"id": doc_id, "response": response})

        return {"result": "deleted", "docs": deleted_docs}


@app.delete("/delete_tool/{name}")
async def delete_tool(name: str):
    async with AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    ) as client:
        # 1) Search for docs where raw.name matches (no nested)
        res = await client.search(
            index="tools",
            body={
                "query": {
                    "term": {"raw.name.keyword": name}  # exact match
                }
            },
            size=100,
        )

        hits = res["hits"]["hits"]
        if not hits:
            raise HTTPException(status_code=404, detail="Tool not found")

        # 2) Delete each matching doc
        deletes = []
        for hit in hits:
            doc_id = hit["_id"]
            resp = await client.delete(index="tools", id=doc_id)
            deletes.append({"id": doc_id, "result": resp})

        return {"deleted": deletes}


@app.put("/update_agent/{name}")
async def update_agent(name: str, raw: dict):
    async with AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    ) as client:
        res = await client.search(
            index="agents",
            body={"query": {"term": {"raw.agent_name.keyword": name}}},
            size=1,
        )

        hits = res["hits"]["hits"]
        if not hits:
            raise HTTPException(status_code=404, detail="Agent not found")

        doc_id = hits[0]["_id"]
        updated = await client.update(
            index="agents", id=doc_id, body={"doc": {"raw": raw}}
        )

        return {"result": "updated", "id": doc_id, "update_response": updated}


@app.put("/update_tool/{name}")
async def update_tool(name: str, raw: dict):
    async with AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    ) as client:
        # 1) Search by exact tool_name
        res = await client.search(
            index="tools",
            body={"query": {"term": {"raw.name.keyword": name}}},
            size=1,
        )

        hits = res["hits"]["hits"]
        if not hits:
            raise HTTPException(status_code=404, detail="Tool not found")

        doc_id = hits[0]["_id"]

        # 2) Update only raw
        update_response = await client.update(
            index="tools", id=doc_id, body={"doc": {"raw": raw}}
        )

        return {"result": "updated", "id": doc_id, "update_response": update_response}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8006, reload=True)
