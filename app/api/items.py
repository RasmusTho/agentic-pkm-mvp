from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import limiter, rate_limit_default, require_api_key
from app.deps import get_db
from app.models import Item

router = APIRouter(
    prefix="/items",
    tags=["items"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", status_code=200)
@limiter.limit(lambda: rate_limit_default())
def create_item(
    request: Request,
    name: str,
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
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
@limiter.limit(lambda: rate_limit_default())
def list_items(
    request: Request,
    db: Session = Depends(get_db),
) -> list[dict[str, int | str]]:
    items = db.query(Item).order_by(Item.id.asc()).all()
    return [{"id": item.id, "name": item.name} for item in items]
