from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


# --- auth -------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(default="", max_length=200)
    organization: str = Field(default="", max_length=200)

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str) -> str:
        if value.isdigit() or value.isalpha():
            raise ValueError("Password must combine letters with numbers or symbols.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: "UserResponse"


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    organization: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- sessions ---------------------------------------------------------------
class SessionSummary(BaseModel):
    id: str
    name: str
    original_filename: str
    file_size: int
    status: str
    error: str = ""
    created_at: datetime
    updated_at: datetime
    workbook_meta: dict[str, Any] = Field(default_factory=dict)
    progress: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    file_deleted: bool = False
    result_expires_at: datetime | None = None

    model_config = {"from_attributes": True}


class ColumnOverride(BaseModel):
    """A user's correction to one column's classification."""

    role: Literal["measure", "dimension", "time", "identifier", "descriptive"] | None = None
    semantic_type: str | None = Field(default=None, max_length=40)
    aggregation: Literal["sum", "mean"] | None = None


class ColumnOverrideRequest(BaseModel):
    overrides: dict[str, ColumnOverride] = Field(default_factory=dict)
    reanalyze: bool = True

    @field_validator("overrides")
    @classmethod
    def _bounded(cls, value: dict[str, "ColumnOverride"]) -> dict[str, "ColumnOverride"]:
        if len(value) > 200:
            raise ValueError("At most 200 column corrections can be sent at once.")
        return value


class CleaningFix(BaseModel):
    id: str = Field(max_length=120)
    type: Literal["standardize_categories", "parse_numeric", "parse_dates",
                  "drop_duplicate_rows"]
    column: str = Field(default="", max_length=300)
    title: str = Field(default="", max_length=300)
    params: dict[str, Any] = Field(default_factory=dict)


class CleaningRequest(BaseModel):
    fixes: list[CleaningFix] = Field(default_factory=list, max_length=25)
    reanalyze: bool = True


class JoinRequest(BaseModel):
    left: str = Field(max_length=200)
    right: str = Field(max_length=200)
    key: str = Field(max_length=300)
    how: Literal["inner", "left", "right", "outer"] = "inner"
    name: str | None = Field(default=None, max_length=200)


class FeedbackRequest(BaseModel):
    insight_id: str = Field(max_length=32)
    vote: Literal["useful", "not_useful", "clear"]
    comment: str = Field(default="", max_length=1000)


class SessionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    notes: dict[str, str] | None = None
    bookmarks: list[str] | None = None


class AnalyzeRequest(BaseModel):
    sheet: str | None = None
    scope: Literal["workbook", "sheet"] = "workbook"


# --- analysis interaction ---------------------------------------------------
class FilterSpec(BaseModel):
    column: str
    type: Literal["multi_select", "date_range", "numeric_range"]
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None

    model_config = {"populate_by_name": True}

    def to_engine(self) -> dict[str, Any]:
        return {
            "column": self.column, "type": self.type, "values": self.values,
            "min": self.min, "max": self.max, "from": self.from_, "to": self.to,
        }


class FilterRequest(BaseModel):
    filters: list[FilterSpec] = Field(default_factory=list, max_length=30)


class DrilldownRequest(BaseModel):
    dimension: str
    value: str
    measure: str | None = None
    filters: list[FilterSpec] = Field(default_factory=list, max_length=30)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    filters: list[FilterSpec] = Field(default_factory=list, max_length=30)
    # The previous answer's ``context`` block, echoed back so a follow-up such
    # as "and what about the North region?" resolves. The conversation lives in
    # the client, not in server state, so nothing has to be expired or isolated.
    context: dict[str, Any] | None = None


class ReportRequest(BaseModel):
    style: Literal["executive", "standard", "detailed"] = "standard"
    title: str | None = Field(default=None, max_length=180)
    organization: str | None = Field(default=None, max_length=120)
    author: str | None = Field(default=None, max_length=120)
    date_range: str | None = Field(default=None, max_length=80)
    audience: Literal["executive", "manager", "analyst", "researcher", "student", "general"] = "manager"
    sections: list[str] | None = None
    include_charts: bool = True
    logo_base64: str | None = Field(default=None, max_length=4_000_000)
    filters: list[FilterSpec] = Field(default_factory=list, max_length=30)


class ExcelExportRequest(BaseModel):
    include_data: bool = False
    data_row_limit: int = Field(default=20_000, ge=1, le=200_000)
    filters: list[FilterSpec] = Field(default_factory=list, max_length=30)


class DataQuery(BaseModel):
    limit: int = Field(default=100, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)
    sort_by: str | None = None
    sort_desc: bool = False
    search: str | None = Field(default=None, max_length=200)
    columns: list[str] | None = None
    filters: list[FilterSpec] = Field(default_factory=list, max_length=30)


class ShareRequest(BaseModel):
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 30)


TokenResponse.model_rebuild()
