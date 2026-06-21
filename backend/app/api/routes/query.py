from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.security import Principal, get_principal
from app.schemas.query import QueryRequest, QueryResponse, ReasoningEvent, TokenEvent
from app.services.agent_query import AgentQueryService

router = APIRouter()
CURRENT_PRINCIPAL = Depends(get_principal)


@router.post("", response_model=QueryResponse)
def query(
    request: QueryRequest, principal: Principal | None = CURRENT_PRINCIPAL
) -> QueryResponse:
    return AgentQueryService().answer(request, principal)


@router.post("/stream")
def query_stream(
    request: QueryRequest, principal: Principal | None = CURRENT_PRINCIPAL
) -> StreamingResponse:
    def event_stream():
        # Leading comment flushes headers immediately so the client opens the
        # stream before the first token arrives.
        yield ": stream-open\n\n"
        for event in AgentQueryService().answer_events(request, principal):
            if isinstance(event, QueryResponse):
                name = "final"
            elif isinstance(event, TokenEvent):
                name = "token"
            elif isinstance(event, ReasoningEvent):
                name = "reasoning"
            else:
                name = "trace"
            yield f"event: {name}\n"
            yield f"data: {event.model_dump_json()}\n\n"

    # Anti-buffering headers: `no-transform` stops proxies/extensions from
    # buffering or rewriting the stream, `X-Accel-Buffering: no` disables nginx
    # buffering. Without these, some setups deliver the whole response at once.
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=headers
    )
