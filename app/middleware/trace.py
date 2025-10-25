from starlette.middleware.base import BaseHTTPMiddleware
import uuid

class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response
