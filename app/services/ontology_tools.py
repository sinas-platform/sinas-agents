"""Ontology tools for LLM to query and write business data."""
from typing import List, Dict, Any, Optional
import uuid as uuid_lib
from datetime import datetime

from sqlalchemy import select, and_, or_, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ontology import (
    Concept, Property, Relationship, DataSource,
    ConceptQuery, Endpoint, EndpointProperty, EndpointFilter
)
from app.models.user import GroupMember
from app.models.assistant import Assistant
from app.core.permissions import check_permission
from app.services.ontology.ontology_utils import (
    get_user_group_ids as util_get_user_group_ids,
    has_wildcard_ontology_access,
    get_concept_by_name,
    get_concept_properties,
    get_dynamic_table_name
)


class OntologyTools:
    """Provides LLM tools for interacting with ontology and business data."""

    @staticmethod
    async def get_tool_definitions(
        db: Optional[AsyncSession] = None,
        user_id: Optional[str] = None,
        ontology_namespaces: Optional[List[str]] = None,
        ontology_concepts: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get OpenAI-compatible tool definitions for ontology operations.

        Args:
            db: Optional database session for enriching tool descriptions
            user_id: Optional user ID for personalizing tool descriptions
            ontology_namespaces: List of allowed namespaces (None = all)
            ontology_concepts: List of allowed concepts in format "namespace.concept" (None = all)

        Returns:
            List of tool definitions
        """
        # Opt-in: None or empty namespaces = no access
        if ontology_namespaces is None or len(ontology_namespaces) == 0:
            return []
        # Empty concepts list means "all concepts in allowed namespaces"
        # So we don't check concepts here

        # Get available concepts if db and user_id provided
        available_concepts_info = ""
        if db and user_id:
            available_concepts_info = await OntologyTools._get_available_concepts_description(
                db, user_id, ontology_namespaces, ontology_concepts
            )

        explore_description = (
            "Explore the business ontology to understand available concepts (entities), "
            "their properties (attributes), and relationships. Use this to discover what "
            "business data is available and how different entities relate to each other. "
            "Examples: exploring customer concepts, finding product properties, discovering "
            "order-customer relationships."
        )

        if available_concepts_info:
            explore_description += f"\n\n{available_concepts_info}"

        return [
            {
                "type": "function",
                "function": {
                    "name": "explore_ontology",
                    "description": explore_description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "concept_name": {
                                "type": "string",
                                "description": "Name of a specific concept to explore (e.g., 'Customer', 'Order')"
                            },
                            "namespace": {
                                "type": "string",
                                "description": "Namespace to filter concepts by (e.g., 'sales', 'inventory')"
                            },
                            "include_properties": {
                                "type": "boolean",
                                "description": "Include properties/attributes of concepts",
                                "default": True
                            },
                            "include_relationships": {
                                "type": "boolean",
                                "description": "Include relationships between concepts",
                                "default": True
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "query_ontology_records",
                    "description": (
                        "Query records from ontology concepts. Retrieve data from self-managed concepts "
                        "or execute pre-configured queries for external data sources. "
                        "Examples: fetching deals, retrieving companies, listing customers."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "concept": {
                                "type": "string",
                                "description": "Concept name to query (e.g., 'Customer', 'Order', 'Product')"
                            },
                            "namespace": {
                                "type": "string",
                                "description": "Namespace of the concept (if known)"
                            },
                            "properties": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Specific properties to retrieve (if not specified, returns all)"
                            },
                            "filters": {
                                "type": "object",
                                "description": (
                                    "Filters to apply (e.g., {'customer_id': '123', 'status': 'active'}). "
                                    "Available operators will be shown after exploring the concept."
                                )
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of records to return",
                                "default": 10
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Offset for pagination",
                                "default": 0
                            }
                        },
                        "required": ["concept"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_ontology_data_record",
                    "description": (
                        "Create a new data record for self-managed ontology concepts (concepts stored "
                        "directly in SINAS database). Only works for concepts marked as self-managed. "
                        "Examples: creating a new customer record, adding a new product, registering an order."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "concept": {
                                "type": "string",
                                "description": "Self-managed concept name (e.g., 'Customer', 'Order')"
                            },
                            "namespace": {
                                "type": "string",
                                "description": "Namespace of the concept"
                            },
                            "data": {
                                "type": "object",
                                "description": "Property values for the new record (e.g., {'name': 'John', 'email': 'john@example.com'})"
                            }
                        },
                        "required": ["concept", "data"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_ontology_data_record",
                    "description": (
                        "Update an existing ontology data record for self-managed concepts. "
                        "Only works for concepts stored in SINAS database."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "concept": {
                                "type": "string",
                                "description": "Self-managed concept name"
                            },
                            "namespace": {
                                "type": "string",
                                "description": "Namespace of the concept"
                            },
                            "record_id": {
                                "type": "string",
                                "description": "ID of the record to update"
                            },
                            "data": {
                                "type": "object",
                                "description": "Property values to update"
                            }
                        },
                        "required": ["concept", "record_id", "data"]
                    }
                }
            }
        ]

    @staticmethod
    async def execute_tool(
        db: AsyncSession,
        tool_name: str,
        arguments: Dict[str, Any],
        user_id: str,
        group_id: Optional[str] = None,
        assistant_id: Optional[str] = None,
        permissions: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """
        Execute an ontology tool.

        Args:
            db: Database session
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            user_id: User ID
            group_id: Optional group ID for group-scoped ontology access
            assistant_id: Optional assistant ID for checking ontology access restrictions

        Returns:
            Tool execution result
        """
        # Check assistant-level restrictions before executing
        if assistant_id and tool_name in ["explore_ontology", "query_ontology_records", "create_ontology_data_record", "update_ontology_data_record"]:
            can_access = await OntologyTools._check_assistant_ontology_access(
                db, assistant_id, arguments
            )
            if not can_access:
                return {
                    "error": "Assistant is not authorized to access this ontology namespace/concept",
                    "suggestion": "Configure assistant's ontology_namespaces and ontology_concepts to allow access"
                }

        if tool_name == "explore_ontology":
            return await OntologyTools._explore_ontology(
                db, user_id, arguments, group_id, permissions
            )
        elif tool_name == "query_ontology_records":
            return await OntologyTools._query_ontology_records(
                db, user_id, arguments, group_id, permissions
            )
        elif tool_name == "create_ontology_data_record":
            return await OntologyTools._create_ontology_data_record(
                db, user_id, arguments, group_id, permissions
            )
        elif tool_name == "update_ontology_data_record":
            return await OntologyTools._update_ontology_data_record(
                db, user_id, arguments, group_id, permissions
            )
        else:
            return {"error": f"Unknown ontology tool: {tool_name}"}

    @staticmethod
    async def _check_assistant_ontology_access(
        db: AsyncSession,
        assistant_id: str,
        arguments: Dict[str, Any]
    ) -> bool:
        """
        Check if assistant is allowed to access the requested ontology namespace/concept.

        Args:
            db: Database session
            assistant_id: Assistant ID
            arguments: Tool arguments containing namespace and/or concept

        Returns:
            True if access is allowed, False otherwise
        """
        # Get assistant
        result = await db.execute(
            select(Assistant).where(Assistant.id == uuid_lib.UUID(assistant_id))
        )
        assistant = result.scalar_one_or_none()

        if not assistant:
            return True  # If assistant doesn't exist, don't restrict

        # Extract namespace and concept from arguments
        namespace = arguments.get("namespace")
        concept = arguments.get("concept") or arguments.get("concept_name")

        # If ontology_namespaces is None, no access (opt-in)
        if assistant.ontology_namespaces is None:
            return False

        # If namespace is provided, check if it's in allowed namespaces
        if namespace and namespace not in assistant.ontology_namespaces:
            return False

        # If ontology_concepts is None or empty, allow all concepts in allowed namespaces
        if not assistant.ontology_concepts:  # Treats None and [] the same
            return True

        # If ontology_concepts is specified, check if concept is allowed
        if concept:
            # Check namespace.concept format
            if namespace:
                full_concept = f"{namespace}.{concept}"
                if full_concept in assistant.ontology_concepts:
                    return True
            # Also check if just concept name is in the list
            if concept in assistant.ontology_concepts:
                return True
            return False

        # No specific concept requested, allowed if namespace is allowed
        return True

    @staticmethod
    async def _get_available_concepts_description(
        db: AsyncSession,
        user_id: str,
        ontology_namespaces: Optional[List[str]] = None,
        ontology_concepts: Optional[List[str]] = None
    ) -> str:
        """
        Get a summary of available concepts for this user.

        Args:
            db: Database session
            user_id: User ID
            ontology_namespaces: List of allowed namespaces (None = all)
            ontology_concepts: List of allowed concepts in format "namespace.concept" (None = all)

        Returns:
            Formatted string describing available concepts
        """
        user_groups = await OntologyTools._get_user_groups(db, user_id)

        # Query all available concepts
        query = select(
            Concept.namespace,
            Concept.name,
            Concept.display_name
        ).where(
            Concept.group_id.in_(user_groups) if user_groups else False
        )

        # Apply namespace filter if specified
        if ontology_namespaces is not None:
            query = query.where(Concept.namespace.in_(ontology_namespaces))

        query = query.order_by(Concept.namespace, Concept.name)

        result = await db.execute(query)
        concepts = result.all()

        if not concepts:
            return ""

        # Filter by specific concepts if provided
        if ontology_concepts is not None:
            filtered_concepts = []
            for namespace, name, display_name in concepts:
                concept_key = f"{namespace}.{name}"
                if concept_key in ontology_concepts:
                    filtered_concepts.append((namespace, name, display_name))
            concepts = filtered_concepts

        if not concepts:
            return ""

        # Group by namespace
        by_namespace: Dict[str, List[tuple]] = {}
        for namespace, name, display_name in concepts:
            if namespace not in by_namespace:
                by_namespace[namespace] = []
            by_namespace[namespace].append((name, display_name))

        # Format as readable list
        lines = ["Available concepts:"]
        for namespace in sorted(by_namespace.keys()):
            concept_list = by_namespace[namespace]
            formatted_concepts = ", ".join([f"'{name}'" for name, _ in concept_list])
            lines.append(f"  • {namespace}: {formatted_concepts}")

        return "\n".join(lines)

    @staticmethod
    async def _get_user_groups(db: AsyncSession, user_id: str) -> List[uuid_lib.UUID]:
        """Get all group IDs that the user is a member of."""
        user_uuid = uuid_lib.UUID(user_id)
        return await util_get_user_group_ids(db, user_uuid)

    @staticmethod
    async def _explore_ontology(
        db: AsyncSession,
        user_id: str,
        args: Dict[str, Any],
        group_id: Optional[str],
        permissions: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """Explore the ontology structure."""
        # Check if user has wildcard ontology read permission (admins)
        wildcard_access = has_wildcard_ontology_access(permissions)

        # Build query based on permissions
        if wildcard_access:
            # Admin can see all concepts
            query = select(Concept)
        else:
            # Get user's groups
            user_groups = await OntologyTools._get_user_groups(db, user_id)

            if group_id:
                # Filter by specific group
                group_filter = Concept.group_id == uuid_lib.UUID(group_id)
            else:
                # Include all user's groups
                group_filter = Concept.group_id.in_(user_groups) if user_groups else False

            query = select(Concept).where(group_filter)

        if "concept_name" in args and args["concept_name"]:
            # Use case-insensitive exact match or partial match
            concept_name = args["concept_name"]
            query = query.where(
                or_(
                    func.lower(Concept.name) == func.lower(concept_name),
                    Concept.name.ilike(f"%{concept_name}%")
                )
            )

        if "namespace" in args and args["namespace"]:
            query = query.where(Concept.namespace == args["namespace"])

        result = await db.execute(query)
        concepts = result.scalars().all()

        if not concepts:
            return {
                "success": True,
                "message": "No matching concepts found in your accessible groups",
                "concepts": []
            }

        # Build response
        concept_data = []
        for concept in concepts:
            concept_info = {
                "namespace": concept.namespace,
                "name": concept.name,
                "display_name": concept.display_name,
                "description": concept.description,
                "is_self_managed": concept.is_self_managed
            }

            # Include properties if requested
            if args.get("include_properties", True):
                result = await db.execute(
                    select(Property).where(Property.concept_id == concept.id)
                )
                properties = result.scalars().all()
                concept_info["properties"] = [
                    {
                        "name": prop.name,
                        "display_name": prop.display_name,
                        "description": prop.description,
                        "data_type": prop.data_type.value,
                        "is_identifier": prop.is_identifier,
                        "is_required": prop.is_required
                    }
                    for prop in properties
                ]

            # Include relationships if requested
            if args.get("include_relationships", True):
                result = await db.execute(
                    select(Relationship).where(
                        or_(
                            Relationship.from_concept_id == concept.id,
                            Relationship.to_concept_id == concept.id
                        )
                    )
                )
                relationships = result.scalars().all()

                concept_info["relationships"] = []
                for rel in relationships:
                    # Get related concept
                    related_concept_id = (
                        rel.to_concept_id if rel.from_concept_id == concept.id
                        else rel.from_concept_id
                    )
                    result = await db.execute(
                        select(Concept).where(Concept.id == related_concept_id)
                    )
                    related_concept = result.scalar_one_or_none()

                    if related_concept:
                        concept_info["relationships"].append({
                            "name": rel.name,
                            "cardinality": rel.cardinality.value,
                            "direction": "from" if rel.from_concept_id == concept.id else "to",
                            "related_concept": f"{related_concept.namespace}.{related_concept.name}",
                            "description": rel.description
                        })

            concept_data.append(concept_info)

        return {
            "success": True,
            "count": len(concept_data),
            "concepts": concept_data
        }

    @staticmethod
    async def _query_ontology_records(
        db: AsyncSession,
        user_id: str,
        args: Dict[str, Any],
        group_id: Optional[str],
        permissions: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """Query records from ontology concepts."""
        # Use shared helper to get concept with access control
        concept = await get_concept_by_name(
            db=db,
            concept_name=args["concept"],
            namespace=args.get("namespace"),
            user_id=user_id,
            permissions=permissions,
            group_id=group_id
        )

        if not concept:
            return {
                "error": f"Concept '{args['concept']}' not found in accessible groups",
                "suggestion": "Use explore_ontology to see available concepts"
            }

        # For self-managed concepts, query the dynamic table
        if concept.is_self_managed:
            table_name = get_dynamic_table_name(concept)

            # Build SELECT query
            limit = args.get("limit", 10)
            offset = args.get("offset", 0)

            # Get properties to select
            properties_to_select = args.get("properties", [])
            if properties_to_select:
                columns = ", ".join(properties_to_select)
            else:
                columns = "*"

            # Build WHERE clause from filters
            where_clauses = []
            params = {}
            if "filters" in args and args["filters"]:
                for i, (key, value) in enumerate(args["filters"].items()):
                    param_name = f"filter_{i}"
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            # Execute query
            query_sql = text(f"""
                SELECT {columns}
                FROM {table_name}
                {where_sql}
                LIMIT :limit OFFSET :offset
            """)
            params['limit'] = limit
            params['offset'] = offset

            try:
                result = await db.execute(query_sql, params)
                rows = result.mappings().all()

                # Convert records to JSON-serializable format
                records = []
                for row in rows:
                    record = {}
                    for key, value in row.items():
                        # Handle special types
                        if isinstance(value, datetime):
                            record[key] = value.isoformat()
                        elif hasattr(value, '__float__'):  # Decimal, float, etc
                            record[key] = float(value)
                        elif isinstance(value, uuid_lib.UUID):
                            record[key] = str(value)
                        else:
                            record[key] = value
                    records.append(record)

                return {
                    "success": True,
                    "concept": f"{concept.namespace}.{concept.name}",
                    "count": len(records),
                    "records": records
                }
            except Exception as e:
                return {
                    "error": f"Failed to query records: {str(e)}",
                    "suggestion": "Check your filters and property names"
                }
        else:
            # For external concepts with queries, return not implemented message
            return {
                "success": False,
                "message": (
                    f"Querying external concept '{concept.namespace}.{concept.name}' requires "
                    "endpoint configuration. This feature is not yet implemented."
                ),
                "concept_info": {
                    "namespace": concept.namespace,
                    "name": concept.name,
                    "is_self_managed": concept.is_self_managed
                }
            }

    @staticmethod
    async def _create_ontology_data_record(
        db: AsyncSession,
        user_id: str,
        args: Dict[str, Any],
        group_id: Optional[str],
        permissions: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """Create a new ontology data record for self-managed concepts."""
        from app.api.v1.endpoints.ontology_records import (
            get_user_group_ids, get_concept_with_permissions,
            get_dynamic_table_name, validate_data_against_properties
        )

        user_uuid = uuid_lib.UUID(user_id)

        # Get user's groups
        user_groups = await get_user_group_ids(db, user_uuid)

        # Find the concept
        try:
            # Determine namespace - if not provided, try to find concept by name
            namespace = args.get("namespace")
            if not namespace:
                # Try to find by concept name alone (case-insensitive)
                result = await db.execute(
                    select(Concept).where(
                        and_(
                            func.lower(Concept.name) == func.lower(args["concept"]),
                            Concept.is_self_managed == True,
                            Concept.group_id.in_(user_groups) if user_groups else False
                        )
                    )
                )
                concept = result.scalar_one_or_none()
                if concept:
                    namespace = concept.namespace
                else:
                    return {
                        "error": f"Self-managed concept '{args['concept']}' not found",
                        "suggestion": "Provide both namespace and concept name, or use explore_ontology to find available concepts."
                    }

            concept = await get_concept_with_permissions(
                db, namespace, args["concept"], user_groups
            )
        except Exception as e:
            return {
                "error": f"Concept not found: {str(e)}",
                "suggestion": "Use explore_ontology to see available self-managed concepts."
            }

        # Get concept properties
        result = await db.execute(
            select(Property).where(Property.concept_id == concept.id)
        )
        properties = result.scalars().all()

        # Validate data
        try:
            validated_data = validate_data_against_properties(
                args["data"], properties, is_create=True
            )
        except Exception as e:
            return {"error": f"Validation failed: {str(e)}"}

        # Generate ID and timestamps
        record_id = str(uuid_lib.uuid4())
        validated_data['id'] = record_id
        validated_data['created_at'] = datetime.utcnow()
        validated_data['updated_at'] = datetime.utcnow()

        # Get table name
        table_name = get_dynamic_table_name(concept)

        # Build INSERT statement
        columns = list(validated_data.keys())
        placeholders = [f":{col}" for col in columns]

        insert_sql = text(f"""
            INSERT INTO {table_name} ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
        """)

        try:
            await db.execute(insert_sql, validated_data)
            await db.commit()
        except Exception as e:
            await db.rollback()
            return {"error": f"Failed to create record: {str(e)}"}

        return {
            "success": True,
            "message": f"Created record in {concept.namespace}.{concept.name}",
            "record_id": record_id,
            "data": validated_data
        }

    @staticmethod
    async def _update_ontology_data_record(
        db: AsyncSession,
        user_id: str,
        args: Dict[str, Any],
        group_id: Optional[str],
        permissions: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """Update an existing ontology data record for self-managed concepts."""
        from app.api.v1.endpoints.ontology_records import (
            get_user_group_ids, get_concept_with_permissions,
            get_dynamic_table_name, validate_data_against_properties
        )

        user_uuid = uuid_lib.UUID(user_id)

        # Get user's groups
        user_groups = await get_user_group_ids(db, user_uuid)

        # Find the concept
        try:
            namespace = args.get("namespace")
            if not namespace:
                # Try to find by concept name alone (case-insensitive)
                result = await db.execute(
                    select(Concept).where(
                        and_(
                            func.lower(Concept.name) == func.lower(args["concept"]),
                            Concept.is_self_managed == True,
                            Concept.group_id.in_(user_groups) if user_groups else False
                        )
                    )
                )
                concept = result.scalar_one_or_none()
                if concept:
                    namespace = concept.namespace
                else:
                    return {
                        "error": f"Self-managed concept '{args['concept']}' not found",
                        "suggestion": "Provide both namespace and concept name."
                    }

            concept = await get_concept_with_permissions(
                db, namespace, args["concept"], user_groups
            )
        except Exception as e:
            return {"error": f"Concept not found: {str(e)}"}

        # Get concept properties
        result = await db.execute(
            select(Property).where(Property.concept_id == concept.id)
        )
        properties = result.scalars().all()

        # Validate data
        try:
            validated_data = validate_data_against_properties(
                args["data"], properties, is_create=False
            )
        except Exception as e:
            return {"error": f"Validation failed: {str(e)}"}

        # Add updated_at timestamp
        validated_data['updated_at'] = datetime.utcnow()

        # Get table name
        table_name = get_dynamic_table_name(concept)

        # Build UPDATE statement
        set_clauses = [f"{col} = :{col}" for col in validated_data.keys()]
        validated_data['record_id'] = args["record_id"]

        update_sql = text(f"""
            UPDATE {table_name}
            SET {', '.join(set_clauses)}
            WHERE id = :record_id
        """)

        try:
            result = await db.execute(update_sql, validated_data)
            await db.commit()

            if result.rowcount == 0:
                return {"error": "Record not found"}
        except Exception as e:
            await db.rollback()
            return {"error": f"Failed to update record: {str(e)}"}

        # Fetch updated record
        select_sql = text(f"SELECT * FROM {table_name} WHERE id = :record_id")
        result = await db.execute(select_sql, {"record_id": args["record_id"]})
        row = result.mappings().one_or_none()

        if not row:
            return {"error": "Record not found after update"}

        return {
            "success": True,
            "message": f"Updated record in {concept.namespace}.{concept.name}",
            "record_id": args["record_id"],
            "data": dict(row)
        }
