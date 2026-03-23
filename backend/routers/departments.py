
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from backend.database.connection import get_db
from backend.database import crud
from backend.schemas.schemas import DepartmentResponse

router = APIRouter()


@router.get("/departments", response_model=List[DepartmentResponse])
def get_departments(db: Session = Depends(get_db)):
    departments = crud.get_all_departments(db)
    if not departments:
        raise HTTPException(status_code=404, detail="No departments found")
    return departments