"""
Tag models for flexible resource tagging system.
Supports tagging documents, emails, and other resources with key-value pairs.
"""
from sqlalchemy import String, Text, Boolean, Enum, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List, Dict, Any
import enum
import uuid

from .base import Base, uuid_pk, created_at, updated_at


class ValueType(str, enum.Enum):
    """Type of values a tag can have."""
    FREE_TEXT = "free_text"
    MULTIPLE_CHOICE = "multiple_choice"
    BOOLEAN = "boolean"
    NUMBER = "number"


class ResourceType(str, enum.Enum):
    """Types of resources that can be tagged."""
    DOCUMENT = "document"
    EMAIL = "email"


class ScopeType(str, enum.Enum):
    """Scope where tagger rules apply."""
    FOLDER = "folder"
    INBOX = "inbox"


class TagDefinition(Base):
    """
    Defines available tags and their constraints.
    Example: "year" tag with free_text values, or "quarter" with Q1-Q4 choices.
    """
    __tablename__ = "tag_definitions"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Value constraints
    value_type: Mapped[ValueType] = mapped_column(
        Enum(ValueType), nullable=False
    )
    allowed_values: Mapped[Optional[List[str]]] = mapped_column(JSON)
    # For multiple_choice: ["Q1", "Q2", "Q3", "Q4"]
    # For boolean: ["true", "false"] (auto-set)
    # For others: null

    # Which resource types this tag applies to
    applies_to: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    # ["document", "email"]

    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    # If true, this tag must be set when auto-tagging

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Relationships
    creator: Mapped["User"] = relationship("User")
    instances: Mapped[List["TagInstance"]] = relationship(
        "TagInstance", back_populates="tag_definition", cascade="all, delete-orphan"
    )


class TagInstance(Base):
    """
    An actual tag applied to a resource.
    Example: Document #123 has tag "year" = "2025"
    """
    __tablename__ = "tag_instances"
    __table_args__ = (
        UniqueConstraint(
            'tag_definition_id', 'resource_type', 'resource_id',
            name='uix_tag_resource'
        ),
    )

    id: Mapped[uuid_pk]
    tag_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tag_definitions.id"), nullable=False, index=True
    )

    # Resource being tagged
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType), nullable=False, index=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    # Points to documents.id or emails.id

    # Denormalized for faster queries
    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Denormalized from tag_definition.name

    value: Mapped[Optional[str]] = mapped_column(String(500))
    # The actual tag value, e.g., "2025", "Q3", "true"

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Relationships
    tag_definition: Mapped["TagDefinition"] = relationship(
        "TagDefinition", back_populates="instances"
    )
    creator: Mapped["User"] = relationship("User")


class TaggerRule(Base):
    """
    Configuration for auto-tagging resources using an Assistant.
    Links a folder/inbox to an assistant that extracts specific tags.
    """
    __tablename__ = "tagger_rules"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Scope: where this tagger applies
    scope_type: Mapped[ScopeType] = mapped_column(
        Enum(ScopeType), nullable=False
    )
    folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("folders.id"), index=True
    )
    inbox_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("email_inboxes.id"), index=True
    )

    # Which tags to extract
    tag_definition_ids: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    # List of tag_definition.id UUIDs

    # Which assistant to use (has input/output schema)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assistants.id"), nullable=False, index=True
    )

    # Control
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_trigger: Mapped[bool] = mapped_column(Boolean, default=True)
    # If true, automatically run on resource create/update

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Relationships
    folder: Mapped[Optional["Folder"]] = relationship("Folder")
    inbox: Mapped[Optional["EmailInbox"]] = relationship("EmailInbox")
    assistant: Mapped["Assistant"] = relationship("Assistant")
    creator: Mapped["User"] = relationship("User")
