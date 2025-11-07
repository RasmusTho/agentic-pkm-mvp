from fastapi import APIRouter

router = APIRouter()

@router.get("/dashboard")
def dashboard_root():
    return {"status": "ok"}
