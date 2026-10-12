from pydantic import BaseModel, constr

class StudentCreate(BaseModel):
    name: constr(min_length=1, max_length=255)
    student_uid: constr(min_length=1, max_length=255)

class StudentResponse(BaseModel):
    student_uid: str
    name: str
