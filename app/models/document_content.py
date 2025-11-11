"""
MongoDB model for document content storage.
Only the content body is stored in MongoDB, all metadata is in PostgreSQL.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DocumentContent(BaseModel):
    """Simple MongoDB document for storing document content."""

    # content_id matches the content_id in PostgreSQL Document table
    content_id: str = Field(..., alias="_id")

    # The actual document content
    content: str

    # Version tracking (synced with PostgreSQL)
    version: int = 1

    # Last updated timestamp
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
