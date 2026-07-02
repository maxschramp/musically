from pydantic import BaseModel, ConfigDict


class SettingResponse(BaseModel):
    """Schema for a single setting."""
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    description: str
    category: str


class SettingUpdate(BaseModel):
    """Schema for updating a single setting."""
    value: str


class SettingsBulkUpdate(BaseModel):
    """Schema for bulk updating settings as a key-value dict."""
    settings: dict[str, str]
