from datetime import datetime
from pydantic import BaseModel


class Manifest(BaseModel):
    source_id: str
    source_url: str
    sha256: str
    byte_size: int
    row_count: int
    license: str | None = None
    fetched_at: datetime
    adapter: str
