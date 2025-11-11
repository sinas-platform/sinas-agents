"""API endpoints for tag management."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.auth import get_current_user_with_permissions, set_permission_used
from app.core.permissions import check_permission
from app.models import TagDefinition, TagInstance, TaggerRule, ResourceType
from app.schemas.tag import (
    TagDefinitionCreate,
    TagDefinitionUpdate,
    TagDefinitionResponse,
    TagInstanceCreate,
    TagInstanceResponse,
    TagInstanceWithDefinition,
    TaggerRuleCreate,
    TaggerRuleUpdate,
    TaggerRuleResponse,
    RunTaggerRequest,
    RunTaggerResponse,
    BulkTagRequest,
    BulkRunTaggerRequest,
    BulkRunTaggerResponse,
    TagFilter
)
from app.services.tag_service import TagService

router = APIRouter()


# Response schemas for tag values endpoint
class TagValueCount(BaseModel):
    """A tag value with its count."""
    value: Optional[str]
    count: int


class TagValuesResponse(BaseModel):
    """Response for tag values with counts."""
    tag_name: str
    values: List[TagValueCount]


# Tag Definitions


@router.post("/definitions", response_model=TagDefinitionResponse)
async def create_tag_definition(
    request: Request,
    tag_def: TagDefinitionCreate,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Create a new tag definition."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.definitions.create:group"):
        set_permission_used(request, "sinas.tags.definitions.create:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.definitions.create:group", has_perm=True)

    service = TagService(db)
    tag_definition = await service.create_tag_definition(
        user_id=str(user_id),
        name=tag_def.name,
        display_name=tag_def.display_name,
        value_type=tag_def.value_type,
        applies_to=tag_def.applies_to,
        description=tag_def.description,
        allowed_values=tag_def.allowed_values,
        is_required=tag_def.is_required
    )

    return tag_definition


@router.get("/definitions", response_model=List[TagDefinitionResponse])
async def list_tag_definitions(
    request: Request,
    applies_to: Optional[str] = None,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """List all tag definitions."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.definitions.read:group"):
        set_permission_used(request, "sinas.tags.definitions.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.definitions.read:group", has_perm=True)

    service = TagService(db)
    resource_type = ResourceType(applies_to) if applies_to else None
    tag_definitions = await service.get_tag_definitions(applies_to=resource_type)

    return tag_definitions


@router.get("/definitions/{definition_id}", response_model=TagDefinitionResponse)
async def get_tag_definition(
    request: Request,
    definition_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific tag definition."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.definitions.read:group"):
        set_permission_used(request, "sinas.tags.definitions.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.definitions.read:group", has_perm=True)

    result = await db.execute(
        select(TagDefinition).where(TagDefinition.id == definition_id)
    )
    tag_def = result.scalar_one_or_none()

    if not tag_def:
        raise HTTPException(status_code=404, detail="Tag definition not found")

    return tag_def


@router.patch("/definitions/{definition_id}", response_model=TagDefinitionResponse)
async def update_tag_definition(
    request: Request,
    definition_id: str,
    tag_update: TagDefinitionUpdate,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Update a tag definition."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.definitions.update:group"):
        set_permission_used(request, "sinas.tags.definitions.update:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.definitions.update:group", has_perm=True)

    result = await db.execute(
        select(TagDefinition).where(TagDefinition.id == definition_id)
    )
    tag_def = result.scalar_one_or_none()

    if not tag_def:
        raise HTTPException(status_code=404, detail="Tag definition not found")

    # Update fields
    if tag_update.display_name is not None:
        tag_def.display_name = tag_update.display_name
    if tag_update.description is not None:
        tag_def.description = tag_update.description
    if tag_update.allowed_values is not None:
        tag_def.allowed_values = tag_update.allowed_values
    if tag_update.is_required is not None:
        tag_def.is_required = tag_update.is_required

    await db.commit()
    await db.refresh(tag_def)

    return tag_def


@router.delete("/definitions/{definition_id}")
async def delete_tag_definition(
    request: Request,
    definition_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Delete a tag definition."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.definitions.delete:group"):
        set_permission_used(request, "sinas.tags.definitions.delete:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.definitions.delete:group", has_perm=True)

    result = await db.execute(
        select(TagDefinition).where(TagDefinition.id == definition_id)
    )
    tag_def = result.scalar_one_or_none()

    if not tag_def:
        raise HTTPException(status_code=404, detail="Tag definition not found")

    await db.delete(tag_def)
    await db.commit()

    return {"message": "Tag definition deleted"}


# Tag Instances (Applied Tags)


@router.post("/{resource_type}/{resource_id}/tags", response_model=TagInstanceResponse)
async def apply_tag(
    request: Request,
    resource_type: str,
    resource_id: str,
    tag_create: TagInstanceCreate,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Apply a tag to a resource."""
    user_id, permissions = current_user_data

    # Check permission for the resource type
    perm = f"sinas.tags.{resource_type}.create:own"
    if not check_permission(permissions, perm):
        set_permission_used(request, perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, perm, has_perm=True)

    try:
        resource_type_enum = ResourceType(resource_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resource type")

    service = TagService(db)
    tag_instance = await service.apply_tag(
        user_id=str(user_id),
        tag_definition_id=tag_create.tag_definition_id,
        resource_type=resource_type_enum,
        resource_id=resource_id,
        value=tag_create.value
    )

    return tag_instance


@router.post("/{resource_type}/{resource_id}/tags/bulk", response_model=List[TagInstanceResponse])
async def apply_tags_bulk(
    request: Request,
    resource_type: str,
    resource_id: str,
    bulk_request: BulkTagRequest,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Apply multiple tags to a resource at once."""
    user_id, permissions = current_user_data

    perm = f"sinas.tags.{resource_type}.create:own"
    if not check_permission(permissions, perm):
        set_permission_used(request, perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, perm, has_perm=True)

    try:
        resource_type_enum = ResourceType(resource_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resource type")

    service = TagService(db)
    created_tags = []

    for tag_create in bulk_request.tags:
        tag_instance = await service.apply_tag(
            user_id=str(user_id),
            tag_definition_id=tag_create.tag_definition_id,
            resource_type=resource_type_enum,
            resource_id=resource_id,
            value=tag_create.value
        )
        created_tags.append(tag_instance)

    return created_tags


@router.get("/{resource_type}/{resource_id}/tags", response_model=List[TagInstanceResponse])
async def get_resource_tags(
    request: Request,
    resource_type: str,
    resource_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Get all tags for a resource."""
    user_id, permissions = current_user_data

    perm = f"sinas.tags.{resource_type}.read:own"
    if not check_permission(permissions, perm):
        set_permission_used(request, perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, perm, has_perm=True)

    try:
        resource_type_enum = ResourceType(resource_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resource type")

    service = TagService(db)
    tags = await service.get_resource_tags(
        resource_type=resource_type_enum,
        resource_id=resource_id
    )

    return tags


@router.delete("/{resource_type}/{resource_id}/tags/{tag_id}")
async def delete_tag(
    request: Request,
    resource_type: str,
    resource_id: str,
    tag_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Remove a tag from a resource."""
    user_id, permissions = current_user_data

    perm = f"sinas.tags.{resource_type}.delete:own"
    if not check_permission(permissions, perm):
        set_permission_used(request, perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, perm, has_perm=True)

    result = await db.execute(
        select(TagInstance).where(
            TagInstance.id == tag_id,
            TagInstance.resource_id == resource_id
        )
    )
    tag_instance = result.scalar_one_or_none()

    if not tag_instance:
        raise HTTPException(status_code=404, detail="Tag not found")

    await db.delete(tag_instance)
    await db.commit()

    return {"message": "Tag removed"}


# Tagger Rules


@router.post("/tagger-rules", response_model=TaggerRuleResponse)
async def create_tagger_rule(
    request: Request,
    rule: TaggerRuleCreate,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Create a new tagger rule."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.tagger_rules.create:group"):
        set_permission_used(request, "sinas.tags.tagger_rules.create:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.tagger_rules.create:group", has_perm=True)

    service = TagService(db)
    tagger_rule = await service.create_tagger_rule(
        user_id=str(user_id),
        name=rule.name,
        scope_type=rule.scope_type,
        tag_definition_ids=rule.tag_definition_ids,
        assistant_id=rule.assistant_id,
        folder_id=rule.folder_id,
        inbox_id=rule.inbox_id,
        description=rule.description,
        is_active=rule.is_active,
        auto_trigger=rule.auto_trigger
    )

    return tagger_rule


@router.get("/tagger-rules", response_model=List[TaggerRuleResponse])
async def list_tagger_rules(
    request: Request,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """List all tagger rules."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.tagger_rules.read:group"):
        set_permission_used(request, "sinas.tags.tagger_rules.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.tagger_rules.read:group", has_perm=True)

    result = await db.execute(select(TaggerRule))
    rules = result.scalars().all()

    return rules


@router.get("/tagger-rules/{rule_id}", response_model=TaggerRuleResponse)
async def get_tagger_rule(
    request: Request,
    rule_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific tagger rule."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.tagger_rules.read:group"):
        set_permission_used(request, "sinas.tags.tagger_rules.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.tagger_rules.read:group", has_perm=True)

    result = await db.execute(
        select(TaggerRule).where(TaggerRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Tagger rule not found")

    return rule


@router.patch("/tagger-rules/{rule_id}", response_model=TaggerRuleResponse)
async def update_tagger_rule(
    request: Request,
    rule_id: str,
    rule_update: TaggerRuleUpdate,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Update a tagger rule."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.tagger_rules.update:group"):
        set_permission_used(request, "sinas.tags.tagger_rules.update:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.tagger_rules.update:group", has_perm=True)

    result = await db.execute(
        select(TaggerRule).where(TaggerRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Tagger rule not found")

    # Update fields
    if rule_update.name is not None:
        rule.name = rule_update.name
    if rule_update.description is not None:
        rule.description = rule_update.description
    if rule_update.tag_definition_ids is not None:
        rule.tag_definition_ids = rule_update.tag_definition_ids
    if rule_update.assistant_id is not None:
        rule.assistant_id = rule_update.assistant_id
    if rule_update.is_active is not None:
        rule.is_active = rule_update.is_active
    if rule_update.auto_trigger is not None:
        rule.auto_trigger = rule_update.auto_trigger

    await db.commit()
    await db.refresh(rule)

    return rule


@router.delete("/tagger-rules/{rule_id}")
async def delete_tagger_rule(
    request: Request,
    rule_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Delete a tagger rule."""
    user_id, permissions = current_user_data

    if not check_permission(permissions, "sinas.tags.tagger_rules.delete:group"):
        set_permission_used(request, "sinas.tags.tagger_rules.delete:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.tagger_rules.delete:group", has_perm=True)

    result = await db.execute(
        select(TaggerRule).where(TaggerRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Tagger rule not found")

    await db.delete(rule)
    await db.commit()

    return {"message": "Tagger rule deleted"}


@router.post("/{resource_type}/{resource_id}/run-tagger", response_model=RunTaggerResponse)
async def run_tagger_on_resource(
    request: Request,
    resource_type: str,
    resource_id: str,
    run_request: RunTaggerRequest,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Manually run a tagger on a resource."""
    user_id, permissions, token = current_user_data[0], current_user_data[1], request.headers.get("Authorization", "").replace("Bearer ", "")

    perm = f"sinas.tags.{resource_type}.create:own"
    if not check_permission(permissions, perm):
        set_permission_used(request, perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, perm, has_perm=True)

    try:
        resource_type_enum = ResourceType(resource_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resource type")

    # Get tagger rule ID
    tagger_rule_id = run_request.tagger_rule_id
    if not tagger_rule_id:
        # Try to find auto-trigger rule for this resource
        # Would need folder_id or inbox_id from resource
        raise HTTPException(status_code=400, detail="tagger_rule_id required")

    service = TagService(db)
    try:
        tags_created = await service.run_tagger(
            user_id=str(user_id),
            user_token=token,
            tagger_rule_id=tagger_rule_id,
            resource_type=resource_type_enum,
            resource_id=resource_id
        )

        return RunTaggerResponse(
            success=True,
            tags_created=tags_created,
            message=f"Successfully tagged with {len(tags_created)} tags"
        )
    except Exception as e:
        return RunTaggerResponse(
            success=False,
            tags_created=[],
            message=str(e)
        )


@router.post("/tagger-rules/{rule_id}/run-bulk", response_model=BulkRunTaggerResponse)
async def run_tagger_bulk(
    request: Request,
    rule_id: str,
    bulk_request: BulkRunTaggerRequest,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """
    Run a tagger on all documents in a folder.

    Useful for:
    - Re-tagging documents after adding new tag definitions to a rule
    - Fixing incorrect tags (with force_retag=True)
    - Tagging existing documents in a folder with a new tagger rule
    """
    user_id, permissions, token = current_user_data[0], current_user_data[1], request.headers.get("Authorization", "").replace("Bearer ", "")

    # Check permission
    perm = "sinas.tags.tagger_rules.execute:group"
    if not check_permission(permissions, perm):
        set_permission_used(request, perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, perm, has_perm=True)

    service = TagService(db)

    try:
        result = await service.run_tagger_bulk(
            user_id=str(user_id),
            user_token=token,
            tagger_rule_id=rule_id,
            folder_id=bulk_request.folder_id,
            force_retag=bulk_request.force_retag
        )

        return BulkRunTaggerResponse(
            success=result["documents_failed"] == 0,
            documents_processed=result["documents_processed"],
            documents_failed=result["documents_failed"],
            total_tags_created=result["total_tags_created"],
            errors=result["errors"],
            message=f"Processed {result['documents_processed']} documents, created {result['total_tags_created']} tags"
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/values/{tag_name}", response_model=TagValuesResponse)
async def get_tag_values(
    request: Request,
    tag_name: str,
    resource_type: Optional[str] = None,  # "document" or "email"
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db)
):
    """Get all distinct values for a tag with counts."""
    user_id, permissions = current_user_data

    # Check permission to read tags
    if not check_permission(permissions, "sinas.tags.document.read:group"):
        set_permission_used(request, "sinas.tags.document.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.tags.document.read:group", has_perm=True)

    # Get tag definition
    result = await db.execute(
        select(TagDefinition).where(TagDefinition.name == tag_name)
    )
    tag_def = result.scalar_one_or_none()
    if not tag_def:
        raise HTTPException(status_code=404, detail="Tag definition not found")

    # Build query for tag values with counts
    query = select(
        TagInstance.value,
        func.count(TagInstance.id).label("count")
    ).where(
        TagInstance.tag_definition_id == tag_def.id
    )

    # Filter by resource type if specified
    if resource_type:
        query = query.where(TagInstance.resource_type == resource_type)

    query = query.group_by(TagInstance.value).order_by(func.count(TagInstance.id).desc())

    result = await db.execute(query)
    rows = result.all()

    values = [TagValueCount(value=row[0], count=row[1]) for row in rows]

    return TagValuesResponse(
        tag_name=tag_name,
        values=values
    )
