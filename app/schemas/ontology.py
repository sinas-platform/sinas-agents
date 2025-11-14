"""Pydantic schemas for ontology API."""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.ontology import (
    DataType,
    Cardinality,
    ResponseFormat,
    JoinType,
    SortDirection,
    FilterOperator,
)


# ============================================================================
# DataSource Schemas
# ============================================================================

class DataSourceBase(BaseModel):
    """Base schema for DataSource."""
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., description="Database type: postgres, snowflake, bigquery")
    conn_string: str = Field(..., description="Connection string (will be encrypted)")
    default_database: Optional[str] = None
    default_schema: Optional[str] = None


class DataSourceCreate(DataSourceBase):
    """Schema for creating a DataSource."""
    group_id: UUID


class DataSourceUpdate(BaseModel):
    """Schema for updating a DataSource."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[str] = None
    conn_string: Optional[str] = None
    default_database: Optional[str] = None
    default_schema: Optional[str] = None


class DataSourceResponse(DataSourceBase):
    """Schema for DataSource response."""
    id: UUID
    group_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Concept Schemas
# ============================================================================

class ConceptBase(BaseModel):
    """Base schema for Concept."""
    namespace: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    display_name: Optional[str] = None
    description: Optional[str] = None
    is_self_managed: bool = Field(False, description="True for self-managed concepts (no external source)")


class ConceptCreate(ConceptBase):
    """Schema for creating a Concept."""
    group_id: UUID


class ConceptUpdate(BaseModel):
    """Schema for updating a Concept."""
    display_name: Optional[str] = None
    description: Optional[str] = None
    # Note: namespace, name, is_self_managed cannot be changed after creation


class ConceptResponse(ConceptBase):
    """Schema for Concept response."""
    id: UUID
    group_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Property Schemas
# ============================================================================

class PropertyBase(BaseModel):
    """Base schema for Property."""
    name: str = Field(..., min_length=1, max_length=255)
    display_name: Optional[str] = None
    description: Optional[str] = None
    data_type: DataType
    is_identifier: bool = Field(False, description="Acts as primary key")
    is_required: bool = Field(False, description="Cannot be null")
    is_system: bool = Field(False, description="Auto-generated system property (read-only)")
    default_value: Optional[str] = Field(None, description="Default value as string")


class PropertyCreate(PropertyBase):
    """Schema for creating a Property."""
    concept_id: UUID


class PropertyUpdate(BaseModel):
    """Schema for updating a Property."""
    display_name: Optional[str] = None
    description: Optional[str] = None
    data_type: Optional[DataType] = None
    is_identifier: Optional[bool] = None
    is_required: Optional[bool] = None
    default_value: Optional[str] = None


class PropertyResponse(PropertyBase):
    """Schema for Property response."""
    id: UUID
    concept_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Relationship Schemas
# ============================================================================

class RelationshipBase(BaseModel):
    """Base schema for Relationship."""
    name: str = Field(..., min_length=1, max_length=255)
    cardinality: Cardinality
    description: Optional[str] = None


class RelationshipCreate(RelationshipBase):
    """Schema for creating a Relationship."""
    from_concept_id: UUID
    to_concept_id: UUID
    from_property_id: UUID
    to_property_id: UUID


class RelationshipUpdate(BaseModel):
    """Schema for updating a Relationship."""
    name: Optional[str] = None
    cardinality: Optional[Cardinality] = None
    description: Optional[str] = None


class RelationshipResponse(RelationshipBase):
    """Schema for Relationship response."""
    id: UUID
    from_concept_id: UUID
    to_concept_id: UUID
    from_property_id: UUID
    to_property_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# ConceptQuery Schemas
# ============================================================================

class ConceptQueryBase(BaseModel):
    """Base schema for ConceptQuery."""
    sql_text: Optional[str] = Field(None, description="SQL query (null for self-managed)")
    sync_enabled: bool = Field(False, description="Enable periodic sync to local DB")
    sync_schedule: Optional[str] = Field(None, description="Cron expression for sync")


class ConceptQueryCreate(ConceptQueryBase):
    """Schema for creating a ConceptQuery."""
    concept_id: UUID
    data_source_id: Optional[UUID] = Field(None, description="Null for self-managed concepts")

    @field_validator('data_source_id', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty string to None for optional UUID field."""
        if v == '':
            return None
        return v


class ConceptQueryUpdate(BaseModel):
    """Schema for updating a ConceptQuery."""
    sql_text: Optional[str] = None
    data_source_id: Optional[UUID] = None
    sync_enabled: Optional[bool] = None
    sync_schedule: Optional[str] = None

    @field_validator('data_source_id', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty string to None for optional UUID field."""
        if v == '':
            return None
        return v


class ConceptQueryResponse(ConceptQueryBase):
    """Schema for ConceptQuery response."""
    id: UUID
    concept_id: UUID
    data_source_id: Optional[UUID]
    last_synced_at: Optional[datetime]
    validated_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Endpoint Schemas
# ============================================================================

class EndpointBase(BaseModel):
    """Base schema for Endpoint."""
    name: str = Field(..., min_length=1, max_length=255)
    route: str = Field(..., description="URL route for the endpoint")
    response_format: ResponseFormat = ResponseFormat.JSON
    enabled: bool = True
    description: Optional[str] = None
    limit_default: int = Field(100, ge=1, le=10000)


class EndpointCreate(EndpointBase):
    """Schema for creating an Endpoint."""
    subject_concept_id: UUID


class EndpointUpdate(BaseModel):
    """Schema for updating an Endpoint."""
    name: Optional[str] = None
    route: Optional[str] = None
    response_format: Optional[ResponseFormat] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    limit_default: Optional[int] = Field(None, ge=1, le=10000)


class EndpointResponse(EndpointBase):
    """Schema for Endpoint response."""
    id: UUID
    subject_concept_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# EndpointProperty Schemas
# ============================================================================

class EndpointPropertyBase(BaseModel):
    """Base schema for EndpointProperty."""
    alias: Optional[str] = None
    aggregation: Optional[str] = Field(None, description="Aggregation function: max, avg, count, sum")
    include: bool = True


class EndpointPropertyCreate(EndpointPropertyBase):
    """Schema for creating an EndpointProperty."""
    endpoint_id: UUID
    concept_id: UUID
    property_id: UUID


class EndpointPropertyResponse(EndpointPropertyBase):
    """Schema for EndpointProperty response."""
    id: UUID
    endpoint_id: UUID
    concept_id: UUID
    property_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# EndpointFilter Schemas
# ============================================================================

class EndpointFilterBase(BaseModel):
    """Base schema for EndpointFilter."""
    op: FilterOperator
    param_name: str = Field(..., min_length=1)
    required: bool = False
    default_value: Optional[str] = None


class EndpointFilterCreate(EndpointFilterBase):
    """Schema for creating an EndpointFilter."""
    endpoint_id: UUID
    property_id: UUID


class EndpointFilterResponse(EndpointFilterBase):
    """Schema for EndpointFilter response."""
    id: UUID
    endpoint_id: UUID
    property_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# EndpointOrder Schemas
# ============================================================================

class EndpointOrderBase(BaseModel):
    """Base schema for EndpointOrder."""
    direction: SortDirection = SortDirection.ASC
    priority: int = Field(0, ge=0)


class EndpointOrderCreate(EndpointOrderBase):
    """Schema for creating an EndpointOrder."""
    endpoint_id: UUID
    property_id: UUID


class EndpointOrderResponse(EndpointOrderBase):
    """Schema for EndpointOrder response."""
    id: UUID
    endpoint_id: UUID
    property_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# EndpointJoin Schemas
# ============================================================================

class EndpointJoinBase(BaseModel):
    """Base schema for EndpointJoin."""
    join_type: JoinType = JoinType.INNER


class EndpointJoinCreate(EndpointJoinBase):
    """Schema for creating an EndpointJoin."""
    endpoint_id: UUID
    relationship_id: UUID


class EndpointJoinResponse(EndpointJoinBase):
    """Schema for EndpointJoin response."""
    id: UUID
    endpoint_id: UUID
    relationship_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Query Execution Schemas
# ============================================================================

class QueryExecutionRequest(BaseModel):
    """Schema for executing a query endpoint."""
    filters: dict = Field(default_factory=dict)
    limit: Optional[int] = Field(None, ge=1, le=10000)


class QueryExecutionResponse(BaseModel):
    """Schema for query execution response."""
    data: List[dict]
    count: int


class CompiledQueryResponse(BaseModel):
    """Schema for compiled query response (debugging)."""
    sql: str
    params: dict


# ============================================================================
# Sync Status Schemas
# ============================================================================

class SyncStatusResponse(BaseModel):
    """Schema for sync status response."""
    concept_id: UUID
    sync_enabled: bool
    last_synced_at: Optional[datetime]
    next_sync_at: Optional[datetime]
    sync_schedule: Optional[str]
    status: str  # pending, syncing, completed, failed


class SyncTriggerResponse(BaseModel):
    """Schema for sync trigger response."""
    concept_id: UUID
    triggered: bool
    message: str


# ============================================================================
# Self-Managed Concept Data Schemas
# ============================================================================

class ConceptDataCreate(BaseModel):
    """Schema for creating data in a self-managed concept."""
    data: dict = Field(..., description="Data matching the concept's property schema")


class ConceptDataUpdate(BaseModel):
    """Schema for updating data in a self-managed concept."""
    data: dict = Field(..., description="Partial data to update")


class ConceptDataResponse(BaseModel):
    """Schema for self-managed concept data response."""
    id: UUID
    data: dict
    created_at: datetime
    updated_at: datetime
