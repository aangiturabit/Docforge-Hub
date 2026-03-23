from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from backend.database.connection import get_db
from backend.database import crud
from backend.schemas.schemas import TemplateResponse

router = APIRouter()


@router.get("/templates/{department_id}", response_model=List[TemplateResponse])
def get_templates(department_id: int, db: Session = Depends(get_db)):
    department = crud.get_department_by_id(db, department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
    
    templates = crud.get_templates_by_department(db, department_id)
    if not templates:
        raise HTTPException(status_code=404, detail="No templates found for this department")
    
    return templates