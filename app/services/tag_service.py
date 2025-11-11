"""Tag service for managing tags and executing tagger rules using assistants."""
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TagDefinition, TagInstance, TaggerRule, ResourceType, Document, Assistant
from app.models.email import Email
from app.services.message_service import MessageService

logger = logging.getLogger(__name__)


class TagService:
    """Service for managing tags and executing auto-tagging."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.message_service = MessageService(db)

    async def create_tag_definition(
        self,
        user_id: str,
        name: str,
        display_name: str,
        value_type: str,
        applies_to: List[str],
        description: Optional[str] = None,
        allowed_values: Optional[List[str]] = None,
        is_required: bool = False
    ) -> TagDefinition:
        """Create a new tag definition."""
        tag_def = TagDefinition(
            name=name,
            display_name=display_name,
            description=description,
            value_type=value_type,
            allowed_values=allowed_values,
            applies_to=applies_to,
            is_required=is_required,
            created_by=user_id
        )
        self.db.add(tag_def)
        await self.db.commit()
        await self.db.refresh(tag_def)
        return tag_def

    async def get_tag_definitions(
        self,
        applies_to: Optional[ResourceType] = None
    ) -> List[TagDefinition]:
        """Get all tag definitions, optionally filtered by resource type."""
        query = select(TagDefinition)
        if applies_to:
            query = query.where(TagDefinition.applies_to.contains([applies_to.value]))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def apply_tag(
        self,
        user_id: str,
        tag_definition_id: str,
        resource_type: ResourceType,
        resource_id: str,
        value: Optional[str] = None
    ) -> TagInstance:
        """Apply a tag to a resource."""
        # Get tag definition to get the key
        result = await self.db.execute(
            select(TagDefinition).where(TagDefinition.id == tag_definition_id)
        )
        tag_def = result.scalar_one_or_none()
        if not tag_def:
            raise ValueError("Tag definition not found")

        # Validate resource type
        if resource_type.value not in tag_def.applies_to:
            raise ValueError(f"Tag '{tag_def.name}' does not apply to {resource_type.value}")

        # Validate value if multiple_choice
        if tag_def.value_type == "multiple_choice" and tag_def.allowed_values:
            if value not in tag_def.allowed_values:
                raise ValueError(f"Value must be one of: {', '.join(tag_def.allowed_values)}")

        # Check if tag already exists for this resource
        result = await self.db.execute(
            select(TagInstance).where(
                TagInstance.tag_definition_id == tag_definition_id,
                TagInstance.resource_type == resource_type,
                TagInstance.resource_id == resource_id
            )
        )
        existing_tag = result.scalar_one_or_none()

        if existing_tag:
            # Update existing tag
            existing_tag.value = value
            existing_tag.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
            await self.db.refresh(existing_tag)
            return existing_tag

        # Create new tag instance
        tag_instance = TagInstance(
            tag_definition_id=tag_definition_id,
            resource_type=resource_type,
            resource_id=resource_id,
            key=tag_def.name,
            value=value,
            created_by=user_id
        )
        self.db.add(tag_instance)
        await self.db.commit()
        await self.db.refresh(tag_instance)
        return tag_instance

    async def get_resource_tags(
        self,
        resource_type: ResourceType,
        resource_id: str
    ) -> List[TagInstance]:
        """Get all tags for a resource."""
        result = await self.db.execute(
            select(TagInstance).where(
                TagInstance.resource_type == resource_type,
                TagInstance.resource_id == resource_id
            )
        )
        return list(result.scalars().all())

    async def create_tagger_rule(
        self,
        user_id: str,
        name: str,
        scope_type: str,
        tag_definition_ids: List[str],
        assistant_id: str,
        folder_id: Optional[str] = None,
        inbox_id: Optional[str] = None,
        description: Optional[str] = None,
        is_active: bool = True,
        auto_trigger: bool = True
    ) -> TaggerRule:
        """Create a new tagger rule."""
        # Validate scope
        if scope_type == "folder" and not folder_id:
            raise ValueError("folder_id required for folder scope")
        if scope_type == "inbox" and not inbox_id:
            raise ValueError("inbox_id required for inbox scope")

        # Verify assistant exists
        result = await self.db.execute(
            select(Assistant).where(Assistant.id == assistant_id)
        )
        if not result.scalar_one_or_none():
            raise ValueError("Assistant not found")

        # Verify all tag definitions exist
        for tag_def_id in tag_definition_ids:
            result = await self.db.execute(
                select(TagDefinition).where(TagDefinition.id == tag_def_id)
            )
            if not result.scalar_one_or_none():
                raise ValueError(f"Tag definition {tag_def_id} not found")

        tagger_rule = TaggerRule(
            name=name,
            description=description,
            scope_type=scope_type,
            folder_id=folder_id,
            inbox_id=inbox_id,
            tag_definition_ids=tag_definition_ids,
            assistant_id=assistant_id,
            is_active=is_active,
            auto_trigger=auto_trigger,
            created_by=user_id
        )
        self.db.add(tagger_rule)
        await self.db.commit()
        await self.db.refresh(tagger_rule)
        return tagger_rule

    async def run_tagger(
        self,
        user_id: str,
        user_token: str,
        tagger_rule_id: str,
        resource_type: ResourceType,
        resource_id: str
    ) -> List[TagInstance]:
        """
        Run a tagger rule on a resource using the configured assistant.

        Args:
            user_id: User ID
            user_token: User's JWT or API key
            tagger_rule_id: Tagger rule ID
            resource_type: Type of resource (document, email)
            resource_id: Resource ID

        Returns:
            List of created/updated tag instances
        """
        # Get tagger rule
        result = await self.db.execute(
            select(TaggerRule).where(TaggerRule.id == tagger_rule_id)
        )
        tagger_rule = result.scalar_one_or_none()
        if not tagger_rule:
            raise ValueError("Tagger rule not found")

        if not tagger_rule.is_active:
            raise ValueError("Tagger rule is not active")

        # Get assistant
        result = await self.db.execute(
            select(Assistant).where(Assistant.id == tagger_rule.assistant_id)
        )
        assistant = result.scalar_one_or_none()
        if not assistant:
            raise ValueError("Assistant not found")
        if not assistant.output_schema:
            raise ValueError("Assistant must have output_schema configured for tagging")

        # Get tag definitions
        tag_definitions = []
        for tag_def_id in tagger_rule.tag_definition_ids:
            result = await self.db.execute(
                select(TagDefinition).where(TagDefinition.id == tag_def_id)
            )
            tag_def = result.scalar_one_or_none()
            if tag_def:
                tag_definitions.append({
                    "id": str(tag_def.id),
                    "name": tag_def.name,
                    "display_name": tag_def.display_name,
                    "description": tag_def.description,
                    "value_type": tag_def.value_type.value,
                    "allowed_values": tag_def.allowed_values,
                    "is_required": tag_def.is_required
                })

        # Get resource content
        resource_content = await self._get_resource_content(resource_type, resource_id)

        # Prepare input data for assistant
        input_data = {
            "tag_definitions": tag_definitions
        }

        # Create new chat for this tagging session (fresh context)
        chat = await self.message_service.create_chat_with_assistant(
            assistant_id=str(tagger_rule.assistant_id),
            user_id=user_id,
            input_data=input_data
        )

        # Call assistant with schema enforcement
        try:
            response_message = await self.message_service.send_message(
                chat_id=str(chat.id),
                user_id=user_id,
                user_token=user_token,
                content=resource_content,  # Send the actual content to analyze
                max_tokens=2000,
                template_variables=input_data
            )

            # Parse and validate response against output schema
            # Clean response content - remove markdown code blocks if present
            cleaned_content = response_message.content.strip()
            if cleaned_content.startswith("```json"):
                cleaned_content = cleaned_content[7:]
            if cleaned_content.startswith("```"):
                cleaned_content = cleaned_content[3:]
            if cleaned_content.endswith("```"):
                cleaned_content = cleaned_content[:-3]
            cleaned_content = cleaned_content.strip()

            # Parse JSON
            response = json.loads(cleaned_content, strict=False)

            # Response should be a dict with "tags" array
            tags = response.get("tags", [])
            logger.info(f"Tagger response for {resource_type.value} {resource_id}: {response}")

            # Create a map of tag names to IDs for quick lookup
            tag_name_to_id = {tag_def["name"]: tag_def["id"] for tag_def in tag_definitions}

            # Apply tags to resource
            created_tags = []
            for tag_data in tags:
                tag_name = tag_data.get("tag_name")
                value = tag_data.get("value")

                # Skip if tag_name is missing, empty, or not a string
                if not tag_name or not isinstance(tag_name, str):
                    logger.warning(f"Skipping invalid tag data: {tag_data}")
                    continue

                # Look up tag definition ID by name
                tag_def_id = tag_name_to_id.get(tag_name)
                if not tag_def_id:
                    logger.warning(f"Tag name '{tag_name}' not found in tag definitions")
                    continue

                try:
                    tag_instance = await self.apply_tag(
                        user_id=user_id,
                        tag_definition_id=tag_def_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        value=value
                    )
                    created_tags.append(tag_instance)
                except Exception as e:
                    logger.error(f"Failed to apply tag {tag_name} ({tag_def_id}): {e}")
                    # Continue with other tags

            return created_tags

        except Exception as e:
            logger.error(f"Failed to run tagger: {e}")
            raise ValueError(f"Tagging failed: {str(e)}")

    async def _get_resource_content(
        self,
        resource_type: ResourceType,
        resource_id: str
    ) -> str:
        """Get content from a resource for tagging."""
        if resource_type == ResourceType.DOCUMENT:
            # Get document with content
            result = await self.db.execute(
                select(Document).where(Document.id == resource_id)
            )
            doc = result.scalar_one_or_none()
            if not doc:
                raise ValueError("Document not found")

            # Get content from MongoDB
            from app.core.mongodb import get_document_content_collection
            content_collection = get_document_content_collection()
            content_doc = await content_collection.find_one({"_id": str(doc.content_id)})

            return content_doc.get("content", "") if content_doc else ""

        elif resource_type == ResourceType.EMAIL:
            # Get email
            result = await self.db.execute(
                select(Email).where(Email.id == resource_id)
            )
            email = result.scalar_one_or_none()
            if not email:
                raise ValueError("Email not found")

            # Build content from email fields
            content = f"From: {email.from_address}\n"
            content += f"To: {email.to_addresses}\n"
            content += f"Subject: {email.subject}\n\n"
            content += email.body_text or email.body_html or ""

            return content

        else:
            raise ValueError(f"Unsupported resource type: {resource_type}")

    async def find_tagger_rule_for_resource(
        self,
        resource_type: ResourceType,
        folder_id: Optional[str] = None,
        inbox_id: Optional[str] = None
    ) -> Optional[TaggerRule]:
        """Find active auto-trigger tagger rule for a resource location."""
        query = select(TaggerRule).where(
            TaggerRule.is_active == True,
            TaggerRule.auto_trigger == True
        )

        if folder_id:
            query = query.where(
                TaggerRule.scope_type == "folder",
                TaggerRule.folder_id == folder_id
            )
        elif inbox_id:
            query = query.where(
                TaggerRule.scope_type == "inbox",
                TaggerRule.inbox_id == inbox_id
            )
        else:
            return None

        result = await self.db.execute(query.limit(1))
        return result.scalar_one_or_none()

    async def run_tagger_bulk(
        self,
        user_id: str,
        user_token: str,
        tagger_rule_id: str,
        folder_id: Optional[str] = None,
        force_retag: bool = False
    ) -> dict:
        """
        Run a tagger on multiple documents in a folder.

        Args:
            user_id: User ID
            user_token: User's JWT or API key
            tagger_rule_id: Tagger rule ID
            folder_id: Folder ID to process (if None, uses tagger rule's folder)
            force_retag: If True, re-extract ALL tags. If False, only extract missing tags.

        Returns:
            Dict with results: documents_processed, documents_failed, total_tags_created, errors
        """
        # Get tagger rule
        result = await self.db.execute(
            select(TaggerRule).where(TaggerRule.id == tagger_rule_id)
        )
        tagger_rule = result.scalar_one_or_none()
        if not tagger_rule:
            raise ValueError("Tagger rule not found")

        if not tagger_rule.is_active:
            raise ValueError("Tagger rule is not active")

        # Determine folder to process
        target_folder_id = folder_id or str(tagger_rule.folder_id) if tagger_rule.folder_id else None
        if not target_folder_id:
            raise ValueError("folder_id required when tagger rule is not folder-scoped")

        # Get all documents in the folder
        result = await self.db.execute(
            select(Document).where(Document.folder_id == target_folder_id)
        )
        documents = result.scalars().all()

        documents_processed = 0
        documents_failed = 0
        total_tags_created = 0
        errors = []

        for doc in documents:
            try:
                # If not force_retag, check if document already has all required tags
                if not force_retag:
                    existing_tags = await self.get_resource_tags(
                        resource_type=ResourceType.DOCUMENT,
                        resource_id=str(doc.id)
                    )
                    existing_tag_def_ids = {str(tag.tag_definition_id) for tag in existing_tags}

                    # Check if all tag definitions are already applied
                    missing_tags = set(tagger_rule.tag_definition_ids) - existing_tag_def_ids
                    if not missing_tags:
                        documents_processed += 1
                        continue  # Skip - already has all tags

                # Run tagger on this document
                tags_created = await self.run_tagger(
                    user_id=user_id,
                    user_token=user_token,
                    tagger_rule_id=tagger_rule_id,
                    resource_type=ResourceType.DOCUMENT,
                    resource_id=str(doc.id)
                )

                documents_processed += 1
                total_tags_created += len(tags_created)

            except Exception as e:
                documents_failed += 1
                error_msg = f"Document {doc.name} ({doc.id}): {str(e)}"
                errors.append(error_msg)
                logger.error(f"Failed to tag document {doc.id}: {e}")

        return {
            "documents_processed": documents_processed,
            "documents_failed": documents_failed,
            "total_tags_created": total_tags_created,
            "errors": errors
        }
