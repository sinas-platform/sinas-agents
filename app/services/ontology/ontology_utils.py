"""Shared utilities for ontology operations to avoid circular dependencies."""
from typing import List, Dict, Any, Optional
import uuid as uuid_lib

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ontology import Concept, Property
from app.models.user import GroupMember
from app.core.permissions import check_permission


async def get_user_group_ids(db: AsyncSession, user_id: uuid_lib.UUID) -> List[uuid_lib.UUID]:
    """
    Get all group IDs that the user is a member of.

    Args:
        db: Database session
        user_id: User UUID

    Returns:
        List of group UUIDs
    """
    result = await db.execute(
        select(GroupMember.group_id).where(
            and_(
                GroupMember.user_id == user_id,
                GroupMember.active == True
            )
        )
    )
    return [row[0] for row in result.all()]


def has_wildcard_ontology_access(permissions: Optional[Dict[str, bool]]) -> bool:
    """
    Check if user has wildcard ontology access (admin).

    Args:
        permissions: User permissions dict

    Returns:
        True if user has wildcard access
    """
    return permissions and check_permission(permissions, "sinas.ontology.concepts.*.read:all")


async def get_concept_by_name(
    db: AsyncSession,
    concept_name: str,
    namespace: Optional[str] = None,
    user_id: Optional[str] = None,
    permissions: Optional[Dict[str, bool]] = None,
    group_id: Optional[str] = None,
    is_self_managed: Optional[bool] = None
) -> Optional[Concept]:
    """
    Get a concept by name with proper access control.

    Args:
        db: Database session
        concept_name: Concept name (case-insensitive)
        namespace: Optional namespace filter
        user_id: User ID for group-based access
        permissions: User permissions for wildcard access check
        group_id: Optional specific group filter
        is_self_managed: Optional filter for self-managed concepts

    Returns:
        Concept if found and accessible, None otherwise
    """
    # Check if user has wildcard access (admin)
    wildcard_access = has_wildcard_ontology_access(permissions)

    # Build query
    if wildcard_access:
        # Admin can access all concepts
        query = select(Concept).where(
            func.lower(Concept.name) == func.lower(concept_name)
        )
    else:
        # Get user's groups
        if user_id:
            user_uuid = uuid_lib.UUID(user_id)
            user_groups = await get_user_group_ids(db, user_uuid)
        else:
            user_groups = []

        if group_id:
            group_filter = Concept.group_id == uuid_lib.UUID(group_id)
        else:
            group_filter = Concept.group_id.in_(user_groups) if user_groups else False

        query = select(Concept).where(
            and_(
                group_filter,
                func.lower(Concept.name) == func.lower(concept_name)
            )
        )

    # Add optional filters
    if namespace:
        query = query.where(Concept.namespace == namespace)

    if is_self_managed is not None:
        query = query.where(Concept.is_self_managed == is_self_managed)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_concept_properties(db: AsyncSession, concept_id: uuid_lib.UUID) -> List[Property]:
    """
    Get all properties for a concept.

    Args:
        db: Database session
        concept_id: Concept UUID

    Returns:
        List of Property objects
    """
    result = await db.execute(
        select(Property).where(Property.concept_id == concept_id)
    )
    return list(result.scalars().all())


def get_dynamic_table_name(concept: Concept) -> str:
    """
    Get the dynamic table name for a self-managed concept.

    Args:
        concept: Concept object

    Returns:
        Table name in format: ontology_{namespace}_{concept_name}
    """
    return f"ontology_{concept.namespace}_{concept.name}"
