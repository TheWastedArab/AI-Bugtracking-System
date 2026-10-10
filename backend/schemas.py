import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal['reporter', 'developer', 'manager']
Status = Literal['Open', 'In Progress', 'Resolved', 'Verified', 'Closed']
Severity = Literal['Low', 'Medium', 'High', 'Critical', 'Unclassified']


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Registration(Input):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=72)

    @field_validator('password')
    @classmethod
    def strong_password(cls, value):
        if len(value.encode()) > 72 or not all(re.search(p, value) for p in [r'[A-Z]', r'[0-9]', r'[^\w\s]']):
            raise ValueError('Use an uppercase letter, number, special character, and at most 72 UTF-8 bytes')
        return value


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class ProjectCreate(Input):
    name: str = Field(min_length=1, max_length=150)


class MemberInput(Input):
    user_id: int
    role: Role


class BugCreate(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=20, max_length=20000)
    steps: str = Field(min_length=1, max_length=10000)
    environment: str = Field(min_length=1, max_length=2000)


class BugUpdate(Input):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=20, max_length=20000)
    status: Status | None = None
    severity: Severity | None = None
    assignee_id: int | None = None


class CommentInput(Input):
    body: str = Field(min_length=1, max_length=10000)
