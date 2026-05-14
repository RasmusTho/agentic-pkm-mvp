from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BundleTrigger(BaseModel):
    type: str
    source: Optional[str] = None


class ItemProvenance(BaseModel):
    origin: str
    transformed_by: Optional[str] = None


class IncludedItem(BaseModel):
    artifact_id: str
    path: Optional[str] = None
    chunk_ids: list[str] = Field(default_factory=list)
    reason: str
    source_role: Optional[str] = None
    trust_state: Optional[str] = None
    review_state: Optional[str] = None
    retrieval_score: Optional[float] = None
    provenance: Optional[ItemProvenance] = None


class ExcludedItem(BaseModel):
    artifact_id: str
    reason: str


class AuthorityFlags(BaseModel):
    may_answer: bool = False
    may_orient: bool = False
    may_resurface: bool = False
    may_propose: bool = False
    may_write: bool = False


class ExpiryPosture(BaseModel):
    stale_after: Optional[datetime] = None
    reason: Optional[str] = None


class BundleReceipts(BaseModel):
    retrieval_receipt: Optional[str] = None
    orientation_receipt: Optional[str] = None
    write_proposal_receipt: Optional[str] = None


class BundleScope(BaseModel):
    sphere: Optional[str] = None
    project: Optional[str] = None
    vaults: list[str] = Field(default_factory=list)


class ContextBundle(BaseModel):
    id: str
    created_at: datetime
    trigger: BundleTrigger
    intended_use: list[str] = Field(default_factory=list)
    scope: BundleScope
    included: list[IncludedItem] = Field(default_factory=list)
    excluded: list[ExcludedItem] = Field(default_factory=list)
    authority: AuthorityFlags
    expiry: ExpiryPosture
    receipts: BundleReceipts = Field(default_factory=BundleReceipts)
