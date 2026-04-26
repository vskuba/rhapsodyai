from pydantic import BaseModel
from typing import List


class MdEntry(BaseModel):
    filename: str
    title: str
    group_id: str
    category: str
    language: str
    tags: List[str]
    content: str
