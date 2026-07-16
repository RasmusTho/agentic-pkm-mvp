from starlette.middleware.base import BaseHTTPMiddleware
import uuid

from app.observability.tracer import bind_trace_id, reset_trace_id


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
        request.state.trace_id = trace_id
        # Bind the request trace id into the app.observability.tracer
        # contextvar so JSON log lines emitted while handling this request
        # carry trace_id (#3895).
        token = bind_trace_id(trace_id)
        try:
            response = await call_next(request)
        finally:
            reset_trace_id(token)
        response.headers["x-trace-id"] = trace_id
        return response
