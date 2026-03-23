from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from backend.database.connection import get_db
from backend.database import crud
from backend.schemas.schemas import SessionResponse
from pydantic import BaseModel

router = APIRouter()


# ─────────────────────────────────────────
# REQUEST SCHEMA
# ─────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    department_id: int
    template_id: int


class UpdateSessionStatusRequest(BaseModel):
    status: str


# ─────────────────────────────────────────
# CREATE SESSION
# ─────────────────────────────────────────

@router.post("/sessions", response_model=SessionResponse)
def create_session(
    request: CreateSessionRequest,
    db: Session = Depends(get_db)
):
    department = crud.get_department_by_id(db, request.department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    template = crud.get_template_by_id(db, request.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    session = crud.create_session(
        db=db,
        department_id=request.department_id,
        template_id=request.template_id
    )
    return session


# ─────────────────────────────────────────
# GET SESSION BY ID
# ─────────────────────────────────────────

@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: UUID,
    db: Session = Depends(get_db)
):
    session = crud.get_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ─────────────────────────────────────────
# UPDATE SESSION STATUS
# ─────────────────────────────────────────

@router.patch("/sessions/{session_id}/status", response_model=SessionResponse)
def update_session_status(
    session_id: UUID,
    request: UpdateSessionStatusRequest,
    db: Session = Depends(get_db)
):
    session = crud.get_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    valid_statuses = ["pending", "in_progress", "completed", "failed"]
    if request.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}"
        )

    updated = crud.update_session_status(db, session_id, request.status)
    return updated
