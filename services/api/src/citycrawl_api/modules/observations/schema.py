from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CitizenObservationResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    observation_id: str
    in_boundary: bool
    thumbnail_path: str
    # True when this ingest matched an existing kapso_message_id (a controller retry), so no
    # new observation / R2 object was created. The whatsapp-controller reads this flag.
    deduped: bool = False
