"""
Document and folder models for PostgreSQL.
Metadata is stored in PostgreSQL, content is stored in MongoDB.
"""
from sqlalchemy import String, Text, Boolean, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
import enum
import uuid

from .base import Base, uuid_pk, created_at, updated_at


class OwnerType(str, enum.Enum):
    """Type of folder owner."""
    USER = "user"
    GROUP = "group"


class PermissionScope(str, enum.Enum):
    """Permission scope for folders."""
    OWN = "own"
    GROUP = "group"
    ALL = "all"


class FileType(str, enum.Enum):
    """Supported document file types."""
    MD = "md"
    HTML = "html"
    CODE = "code"
    TXT = "txt"


class Folder(Base):
    """Folder for organizing documents with permission inheritance."""
    __tablename__ = "folders"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Ownership - either user_id or group_id must be set
    owner_type: Mapped[OwnerType] = mapped_column(
        Enum(OwnerType), nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("groups.id"), index=True
    )

    # Permission scope for the folder
    permission_scope: Mapped[PermissionScope] = mapped_column(
        Enum(PermissionScope), default=PermissionScope.OWN, nullable=False
    )

    # Parent folder for nested structure (optional)
    parent_folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("folders.id"), index=True
    )

    # Metadata
    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    # Relationships
    user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[user_id]
    )
    group: Mapped[Optional["Group"]] = relationship(
        "Group", foreign_keys=[group_id]
    )
    creator: Mapped["User"] = relationship(
        "User", foreign_keys=[created_by]
    )
    parent_folder: Mapped[Optional["Folder"]] = relationship(
        "Folder", remote_side="Folder.id", foreign_keys=[parent_folder_id]
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="folder", cascade="all, delete-orphan"
    )


class Document(Base):
    """
    Document with metadata in PostgreSQL and content in MongoDB.
    Permissions are inherited from the parent folder.
    """
    __tablename__ = "documents"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # File metadata
    filetype: Mapped[FileType] = mapped_column(
        Enum(FileType), default=FileType.MD, nullable=False
    )
    source: Mapped[Optional[str]] = mapped_column(String(500))  # URL, import path, etc.

    # Folder association - inherits permissions from folder
    folder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("folders.id"), nullable=False, index=True
    )

    # MongoDB reference for content
    # The actual content is stored in MongoDB with this UUID as the document ID
    content_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)

    # Auto-description webhook
    auto_description_webhook_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("webhooks.id")
    )

    # Ownership and metadata
    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # Version tracking
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    folder: Mapped["Folder"] = relationship(
        "Folder", back_populates="documents"
    )
    user: Mapped["User"] = relationship(
        "User", foreign_keys=[user_id]
    )
    creator: Mapped["User"] = relationship(
        "User", foreign_keys=[created_by]
    )
    webhook: Mapped[Optional["Webhook"]] = relationship("Webhook")
