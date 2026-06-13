from __future__ import annotations

import operator
from typing import Annotated, Any

from typing_extensions import TypedDict

from app.domain.bot import ChunkRef, StatePayload


class AgentState(TypedDict):
    messages: Annotated[list[Any], operator.add]
    chunks_seen: Annotated[list[ChunkRef], operator.add]
    iteration_count: int
    state_payload: StatePayload
