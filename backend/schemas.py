import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal['reporter', 'developer', 'manager']
Status = Literal['Open', 'In Progress', 'Resolved', 'Verified', 'Closed']
Severity = Literal['Low', 'Medium', 'High', 'Critical', 'Unclassified']


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('*', mode='before')
    @classmethod
    def trim_text(cls, value, info):
        return value.strip() if isinstance(value, str) and info.field_name not in ('password', 'current_password') else value


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
    component: str = Field(default='general', min_length=1, max_length=100)
    duplicate_of: int | None = None


class BugUpdate(Input):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=20, max_length=20000)
    steps: str | None = Field(default=None, min_length=1, max_length=10000)
    environment: str | None = Field(default=None, min_length=1, max_length=2000)
    status: Status | None = None
    severity: Severity | None = None
    assignee_id: int | None = None
    component: str | None = Field(default=None, min_length=1, max_length=100)
    duplicate_of: int | None = None
    version: int | None = Field(default=None, ge=1)


class CommentInput(Input):
    body: str = Field(min_length=1, max_length=10000)


class VerifyInput(Input):
    token: str = Field(min_length=32, max_length=200)


class ResendInput(Input):
    email: EmailStr


class Preferences(Input):
    assignment: bool = True
    status: bool = True
    comment: bool = True
    critical: bool = True


class AccountUpdate(Input):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    current_password: str | None = Field(default=None, max_length=72)
    preferences: Preferences | None = None


class ProfileUpdate(Input):
    skills: list[str] = Field(default_factory=list, max_length=50)
    components: list[str] = Field(default_factory=list, max_length=50)
    availability: Literal['Available', 'Busy', 'Unavailable'] = 'Available'
    capacity: int = Field(default=5, ge=1, le=100)
    active: bool = True

    @field_validator('skills', 'components')
    @classmethod
    def valid_tags(cls, values):
        if any(not v.strip() or len(v) > 100 for v in values):
            raise ValueError('Tags must contain 1 to 100 characters')
        return sorted(set(v.strip().lower() for v in values))


class SettingsInput(Input):
    duplicate_threshold: float = Field(default=0.65, ge=0, le=1)
    cold_start_count: int = Field(default=100, ge=10, le=100000)
    rule_severity: bool = False


class AdminUserUpdate(Input):
    active: bool
    global_role: Literal['reporter', 'manager', 'admin']
