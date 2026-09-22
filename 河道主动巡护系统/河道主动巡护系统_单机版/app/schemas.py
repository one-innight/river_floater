from pydantic import BaseModel, Field


class StatusUpdate(BaseModel):
    status: str = Field(description="目标状态")
    note: str = Field(default="", max_length=500)
    handler: str = Field(default="", max_length=100)


class OpenCVCameraStart(BaseModel):
    source: str = Field(default="0", min_length=1, max_length=1000)
    location: str = Field(default="河段 A", min_length=1, max_length=100)
    interval_seconds: float = Field(default=8.0, ge=2.0, le=3600.0)
