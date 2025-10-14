import os
if os.getenv("DEBUGPY") == "1":
    import debugpy
    port = int(os.getenv("DEBUGPY_PORT", "5678"))
    debugpy.listen(("0.0.0.0", port))
    print(f"debugpy listening on 0.0.0.0:{port}")
    if os.getenv("DEBUGPY_WAIT") == "1":
        print("Waiting for debugger attach...")
        debugpy.wait_for_client()

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from db import Base, engine
from models import Item
from deps import get_db

app = FastAPI()

@app.on_event("startup")
def _create_tables():
    Base.metadata.create_all(bind=engine)

@app.get("/")
def root():
    return {"ok": True, "service": "api"}

@app.post("/items")
def create_item(name: str, db: Session = Depends(get_db)):
    from sqlalchemy.exc import IntegrityError
    try:
        item = Item(name=name)
        db.add(item)
        db.commit()
        db.refresh(item)
        return {"id": item.id, "name": item.name}
    except IntegrityError:
        db.rollback()
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Item already exists")

@app.get("/items")
def list_items(db: Session = Depends(get_db)):
    return [{"id": i.id, "name": i.name} for i in db.query(Item).all()]
