from ollama import AsyncClient
from opensearchpy import AsyncOpenSearch

from mcp_server.config.settings import get_settings

ollama_client = AsyncClient()


async def embed_text(query: str):
    res = await ollama_client.embeddings(model="qwen3-embedding:0.6b", prompt=query)
    return res.embedding


async def search_relevent_tools(tool_name: str, tool_description: str):
    combined_query = f"{tool_name} {tool_description}"
    query_vector = await embed_text(query=combined_query)
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
        query_res = await client.search(
            index="tools",
            params={"search_pipeline": "agent_team_rrf"},
            body={
                "size": 3,
                "query": {
                    "hybrid": {
                        "queries": [
                            {
                                "multi_match": {
                                    "query": combined_query,
                                    "fields": [
                                        "name^3",
                                        "search_text",
                                    ],
                                    "type": "best_fields",
                                }
                            },
                            {"knn": {"embedding": {"vector": query_vector, "k": 3}}},
                        ]
                    }
                },
            },
        )
        return [hit["_source"]["raw"] for hit in query_res["hits"]["hits"]]
