from pydantic import BaseModel


class AuthSession(BaseModel):
    user_id: int
    username: str
    role: str