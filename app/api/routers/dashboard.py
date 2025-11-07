from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_root():
    return """<!doctype html>
<html><head><title>Dashboard</title></head>
<body>
  <h1>Interesting Items</h1>
  <p>Smoke dashboard</p>
</body></html>"""
