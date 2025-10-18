from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.deps import get_db
from app.models import Item

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", status_code=200)
def create_item(name: str, db: Session = Depends(get_db)):
    try:
        item = Item(name=name)
        db.add(item)
        db.commit()
        db.refresh(item)
        return {"id": item.id, "name": item.name}
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Item already exists")


@router.get("")
def list_items(db: Session = Depends(get_db)):
    items = db.query(Item).order_by(Item.id.asc()).all()
    return [{"id": i.id, "name": i.name} for i in items]
