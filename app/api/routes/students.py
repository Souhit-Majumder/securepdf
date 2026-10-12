from fastapi import APIRouter, Depends, HTTPException
from app.api.dependencies import get_repository
from app.database.repository import Repository
from app.api.schemas.student import StudentCreate, StudentResponse
import sqlite3

router = APIRouter()

@router.post("/", response_model=StudentResponse)
def create_student(
    student: StudentCreate,
    repo: Repository = Depends(get_repository)
):
    # The repository handles IntegrityError internally and returns existing if it matches?
    # Actually, create_student has a try-except for IntegrityError to return existing.
    db_student = repo.create_student(student.student_uid, student.name)
    return StudentResponse(
        student_uid=db_student.student_uid,
        name=db_student.name
    )
