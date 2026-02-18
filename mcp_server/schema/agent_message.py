from pydantic import BaseModel


class AgentMessage(BaseModel):
    session_id: str
    user_id: str
    query: str
