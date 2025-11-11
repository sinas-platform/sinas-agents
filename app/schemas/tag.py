"""
Pydantic schemas for tag system API requests/responses.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal, Union
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# Tag Definition Schemas

class TagDefinitionCreate(BaseModel):
    """Schema for creating a tag definition."""
    name: str = Field(..., min_length=1, max_length=100, pattern="^[a-z0-9_]+$")
    # Only lowercase, numbers, underscores
    display_name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    value_type: Literal["free_text", "multiple_choice", "boolean", "number"]
    allowed_values: Optional[List[str]] = None
    # Required for multiple_choice, ignored for others
    applies_to: List[Literal["document", "email"]] = Field(..., min_items=1)
    is_required: bool = False

    class Config:
        json_schema_extra = {
            "example": {
                "name": "quarter",
                "display_name": "Fiscal Quarter",
                "description": "The fiscal quarter of the document",
                "value_type": "multiple_choice",
                "allowed_values": ["Q1", "Q2", "Q3", "Q4"],
                "applies_to": ["document", "email"],
                "is_required": False
            }
        }


class TagDefinitionUpdate(BaseModel):
    """Schema for updating a tag definition."""
    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    allowed_values: Optional[List[str]] = None
    is_required: Optional[bool] = None


class TagDefinitionResponse(BaseModel):
    """Schema for tag definition response."""
    model_config = ConfigDict(from_attributes=True)

    id: Union[str, UUID]
    name: str
    display_name: str
    description: Optional[str]
    value_type: str
    allowed_values: Optional[List[str]]
    applies_to: List[str]
    is_required: bool
    created_at: datetime
    updated_at: datetime
    created_by: Union[str, UUID]


# Tag Instance Schemas

class TagInstanceCreate(BaseModel):
    """Schema for manually creating a tag instance."""
    tag_definition_id: str  # UUID
    value: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "tag_definition_id": "123e4567-e89b-12d3-a456-426614174000",
                "value": "2025"
            }
        }


class TagInstanceResponse(BaseModel):
    """Schema for tag instance response."""
    model_config = ConfigDict(from_attributes=True)

    id: Union[str, UUID]
    tag_definition_id: Union[str, UUID]
    resource_type: str
    resource_id: Union[str, UUID]
    key: str  # Tag name
    value: Optional[str]
    created_at: datetime
    updated_at: datetime
    created_by: Union[str, UUID]


class TagInstanceWithDefinition(BaseModel):
    """Tag instance with full definition included."""
    model_config = ConfigDict(from_attributes=True)

    id: Union[str, UUID]
    key: str
    value: Optional[str]
    definition: TagDefinitionResponse
    created_at: datetime


# Tagger Rule Schemas

class TaggerRuleCreate(BaseModel):
    """Schema for creating a tagger rule."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    scope_type: Literal["folder", "inbox"]
    folder_id: Optional[str] = None  # UUID, required if scope_type=folder
    inbox_id: Optional[str] = None  # UUID, required if scope_type=inbox
    tag_definition_ids: List[str] = Field(..., min_items=1)  # UUIDs
    assistant_id: str  # UUID
    is_active: bool = True
    auto_trigger: bool = True

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Financial Documents Auto-Tagger",
                "description": "Automatically tags financial documents in the finance folder",
                "scope_type": "folder",
                "folder_id": "123e4567-e89b-12d3-a456-426614174000",
                "tag_definition_ids": [
                    "223e4567-e89b-12d3-a456-426614174000",
                    "323e4567-e89b-12d3-a456-426614174000"
                ],
                "assistant_id": "423e4567-e89b-12d3-a456-426614174000",
                "is_active": True,
                "auto_trigger": True
            }
        }


class TaggerRuleUpdate(BaseModel):
    """Schema for updating a tagger rule."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    tag_definition_ids: Optional[List[str]] = None
    assistant_id: Optional[str] = None
    is_active: Optional[bool] = None
    auto_trigger: Optional[bool] = None


class TaggerRuleResponse(BaseModel):
    """Schema for tagger rule response."""
    model_config = ConfigDict(from_attributes=True)

    id: Union[str, UUID]
    name: str
    description: Optional[str]
    scope_type: str
    folder_id: Optional[Union[str, UUID]]
    inbox_id: Optional[Union[str, UUID]]
    tag_definition_ids: List[str]
    assistant_id: Union[str, UUID]
    is_active: bool
    auto_trigger: bool
    created_at: datetime
    updated_at: datetime
    created_by: Union[str, UUID]


# Helper Schemas for Tagging Operations

class RunTaggerRequest(BaseModel):
    """Request to manually run a tagger on a resource."""
    tagger_rule_id: Optional[str] = None  # If not provided, use folder/inbox default


class RunTaggerResponse(BaseModel):
    """Response from running a tagger."""
    success: bool
    tags_created: List[TagInstanceResponse]
    message: str


class BulkRunTaggerRequest(BaseModel):
    """Request to run tagger on multiple documents in a folder."""
    folder_id: Optional[str] = None  # If provided, run on all documents in folder
    force_retag: bool = False  # If true, re-extract ALL tags. If false, only extract missing tags

    class Config:
        json_schema_extra = {
            "example": {
                "folder_id": "507f1f77-bcf8-6cd7-9943-9011abcdef12",
                "force_retag": False
            }
        }


class BulkRunTaggerResponse(BaseModel):
    """Response from bulk tagger run."""
    success: bool
    documents_processed: int
    documents_failed: int
    total_tags_created: int
    errors: List[str]
    message: str


class BulkTagRequest(BaseModel):
    """Request to set multiple tags at once."""
    tags: List[TagInstanceCreate]


# Query/Filter Schemas

class TagFilter(BaseModel):
    """Filter for querying resources by tags."""
    key: str
    value: Optional[str] = None
    # If value is None, matches any value for this key

    class Config:
        json_schema_extra = {
            "example": {
                "key": "year",
                "value": "2025"
            }
        }
