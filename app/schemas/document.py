"""
Pydantic schemas for document API requests/responses.
"""
from datetime import datetime
from typing import Optional, Literal, Union
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# Folder Schemas
class FolderCreate(BaseModel):
    """Schema for creating a new folder."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    owner_type: Literal["user", "group"]
    user_id: Optional[str] = None  # UUID string
    group_id: Optional[str] = None  # UUID string
    permission_scope: Literal["own", "group", "all"] = "own"
    parent_folder_id: Optional[str] = None  # UUID as string

    class Config:
        json_schema_extra = {
            "example": {
                "name": "My Documents",
                "description": "Personal document collection",
                "owner_type": "user",
                "user_id": "277c2eee-05c9-486f-8180-5c0e5495fbd6",
                "permission_scope": "own",
            }
        }


class FolderUpdate(BaseModel):
    """Schema for updating an existing folder."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    permission_scope: Optional[Literal["own", "group", "all"]] = None
    parent_folder_id: Optional[str] = None  # UUID as string


class FolderResponse(BaseModel):
    """Schema for folder response."""
    model_config = ConfigDict(from_attributes=True)

    id: Union[str, UUID]
    name: str
    description: Optional[str] = None
    owner_type: Literal["user", "group"]
    user_id: Optional[Union[str, UUID]] = None
    group_id: Optional[Union[str, UUID]] = None
    permission_scope: Literal["own", "group", "all"]
    parent_folder_id: Optional[Union[str, UUID]] = None
    created_at: datetime
    updated_at: datetime
    created_by: Union[str, UUID]


# Document Schemas
class DocumentCreate(BaseModel):
    """Schema for creating a new document."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    content: str
    filetype: Literal["md", "html", "code", "txt"] = "md"
    source: Optional[str] = None
    folder_id: str  # UUID as string
    auto_description_webhook_id: Optional[str] = None  # UUID of webhook
    user_id: str  # UUID string

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Project Overview",
                "description": "Overview of the SINAS project",
                "content": "# SINAS Project\n\nThis is the main project documentation.",
                "filetype": "md",
                "folder_id": "507f1f77-bcf8-6cd7-9943-9011abcdef12",
                "user_id": "277c2eee-05c9-486f-8180-5c0e5495fbd6",
            }
        }


class DocumentUpdate(BaseModel):
    """Schema for updating an existing document."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    content: Optional[str] = None
    filetype: Optional[Literal["md", "html", "code", "txt"]] = None
    source: Optional[str] = None
    folder_id: Optional[str] = None  # UUID as string
    auto_description_webhook_id: Optional[str] = None


class DocumentResponse(BaseModel):
    """Schema for document response (with content)."""
    model_config = ConfigDict(from_attributes=True)

    id: Union[str, UUID]
    name: str
    description: Optional[str] = None
    content: str  # Content is included
    filetype: Literal["md", "html", "code", "txt"]
    source: Optional[str] = None
    folder_id: Union[str, UUID]
    content_id: Union[str, UUID]
    auto_description_webhook_id: Optional[Union[str, UUID]] = None
    created_at: datetime
    updated_at: datetime
    created_by: Union[str, UUID]
    user_id: Union[str, UUID]
    version: int


class DocumentListResponse(BaseModel):
    """Schema for document list response (without content for performance)."""
    model_config = ConfigDict(from_attributes=True)

    id: Union[str, UUID]
    name: str
    description: Optional[str] = None
    filetype: Literal["md", "html", "code", "txt"]
    source: Optional[str] = None
    folder_id: Union[str, UUID]
    content_id: Union[str, UUID]
    auto_description_webhook_id: Optional[Union[str, UUID]] = None
    created_at: datetime
    updated_at: datetime
    created_by: Union[str, UUID]
    user_id: Union[str, UUID]
    version: int


class GenerateDescriptionRequest(BaseModel):
    """Schema for triggering auto-description generation."""

    document_id: str  # UUID as string
