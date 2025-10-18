from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Item

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", status_code=200)
def create_item(name: str, db: Session = Depends(get_db)) -> dict[str, int | str]:
    try:
        item = Item(name=name)
        db.add(item)
        db.commit()
        db.refresh(item)
        return {"id": item.id, "name": item.name}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Item already exists") from exc


@router.get("")
def list_items(db: Session = Depends(get_db)) -> list[dict[str, int | str]]:
    items = db.query(Item).order_by(Item.id.asc()).all()
    return [{"id": item.id, "name": item.name} for item in items]
