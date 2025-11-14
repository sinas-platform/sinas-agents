from sqlalchemy import String, Text, Boolean, ForeignKey, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List, Dict, Any
import uuid

from .base import Base, uuid_pk, created_at, updated_at


class Assistant(Base):
    __tablename__ = "assistants"

    id: Mapped[uuid_pk]
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), index=True
    )  # NULL = workspace-wide
    group_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("groups.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # LLM Configuration
    llm_provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("llm_providers.id"), index=True
    )  # NULL = use default provider
    model: Mapped[Optional[str]] = mapped_column(String(100))  # NULL = use provider's default model
    temperature: Mapped[float] = mapped_column(Float, default=0.7)

    # System Prompt (supports Jinja2 templates)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text)

    # Input/Output Schemas (like Functions)
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # JSON Schema defining what input variables are required/allowed
    # Example: {"type": "object", "properties": {"tag_definitions": {"type": "array"}}}

    output_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # JSON Schema defining expected response structure
    # Empty dict {} means no schema enforcement

    # Few-shot learning: initial message history
    initial_messages: Mapped[Optional[List[Dict[str, str]]]] = mapped_column(JSON)
    # Example: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]

    # Tool access
    enabled_webhooks: Mapped[List[str]] = mapped_column(JSON, default=list)
    enabled_mcp_tools: Mapped[List[str]] = mapped_column(JSON, default=list)
    enabled_assistants: Mapped[List[str]] = mapped_column(JSON, default=list)  # List of assistant IDs
    webhook_parameters: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    mcp_tool_parameters: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Context access
    context_namespaces: Mapped[Optional[List[str]]] = mapped_column(JSON, default=None)  # None = all namespaces
    ontology_namespaces: Mapped[Optional[List[str]]] = mapped_column(JSON, default=None)  # None = all namespaces
    ontology_concepts: Mapped[Optional[List[str]]] = mapped_column(JSON, default=None)  # None = all concepts (format: namespace.concept)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="assistants")
    llm_provider: Mapped[Optional["LLMProvider"]] = relationship("LLMProvider")
    chats: Mapped[List["Chat"]] = relationship("Chat", back_populates="assistant")
