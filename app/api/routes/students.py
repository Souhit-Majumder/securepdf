from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import get_repository, get_current_user_from_session
from app.database.models import User
from app.database.repository import Repository
from app.api.schemas.student import StudentCreate, StudentResponse

router = APIRouter()

@router.post("/", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
def create_student(
    student: StudentCreate,
    current_user: User = Depends(get_current_user_from_session),
    repo: Repository = Depends(get_repository)
):
    db_student = repo.create_student(student.student_uid, student.name)
    return StudentResponse(
        student_uid=db_student.student_uid,
        name=db_student.name
    )
