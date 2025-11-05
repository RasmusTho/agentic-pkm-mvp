from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(
        "<!doctype html><html><body><h1>Interesting Items</h1><ul></ul></body></html>"
    )
