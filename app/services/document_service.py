"""
Document service for managing documents and folders.
Metadata is stored in PostgreSQL, content is stored in MongoDB.
"""
from datetime import datetime
from typing import Optional, List
import uuid as uuid_lib
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.mongodb import get_document_content_collection
from app.models.document import Folder, Document, OwnerType, PermissionScope, FileType
from app.models.document_content import DocumentContent
from app.models.webhook import Webhook
from app.models.execution import TriggerType
from app.models.user import GroupMember
from app.models.tag import ResourceType
from app.schemas.document import (
    FolderCreate,
    FolderUpdate,
    DocumentCreate,
    DocumentUpdate,
)
from app.services.execution_engine import executor
from app.core.permissions import check_permission
import logging

logger = logging.getLogger(__name__)


class DocumentService:
    """Service for document and folder operations."""

    # Folder operations

    @staticmethod
    async def create_folder(
        db: AsyncSession, folder_data: FolderCreate, user_id: str, permissions: dict
    ) -> Folder:
        """
        Create a new folder with permission-based ownership validation.

        - :own - Can only create for themselves
        - :group - Can create for themselves or groups they belong to
        - :all - Can create for any user/group (admin)
        """
        owner_user_id = None
        owner_group_id = None

        if folder_data.owner_type == "user":
            # Check if user has :all permission (admin)
            if check_permission(permissions, "sinas.documents.folders.create:all"):
                # Admin can specify any user_id
                owner_user_id = uuid_lib.UUID(folder_data.user_id) if folder_data.user_id else uuid_lib.UUID(user_id)
            else:
                # Non-admin can only create for themselves
                # Ignore any provided user_id and force to authenticated user
                owner_user_id = uuid_lib.UUID(user_id)

        elif folder_data.owner_type == "group":
            if not folder_data.group_id:
                raise ValueError("group_id is required when owner_type is 'group'")

            # Check if user has :all permission (admin)
            if check_permission(permissions, "sinas.documents.folders.create:all"):
                # Admin can use any group
                owner_group_id = uuid_lib.UUID(folder_data.group_id)
            elif check_permission(permissions, "sinas.documents.folders.create:group"):
                # Verify user is member of the specified group
                result = await db.execute(
                    select(GroupMember).where(
                        GroupMember.user_id == uuid_lib.UUID(user_id),
                        GroupMember.group_id == uuid_lib.UUID(folder_data.group_id),
                        GroupMember.active == True
                    )
                )
                if not result.scalar_one_or_none():
                    raise ValueError("You can only create group folders for groups you belong to")
                owner_group_id = uuid_lib.UUID(folder_data.group_id)
            else:
                # Only :own permission - can't create group resources
                raise ValueError("Insufficient permissions to create group-owned folders")

        folder = Folder(
            name=folder_data.name,
            description=folder_data.description,
            owner_type=OwnerType(folder_data.owner_type),
            user_id=owner_user_id,
            group_id=owner_group_id,
            permission_scope=PermissionScope(folder_data.permission_scope),
            parent_folder_id=uuid_lib.UUID(folder_data.parent_folder_id)
            if folder_data.parent_folder_id
            else None,
            created_by=uuid_lib.UUID(user_id),
        )

        db.add(folder)
        await db.commit()
        await db.refresh(folder)
        return folder

    @staticmethod
    async def get_folder(db: AsyncSession, folder_id: str) -> Optional[Folder]:
        """Get a folder by ID."""
        result = await db.execute(select(Folder).where(Folder.id == uuid_lib.UUID(folder_id)))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_folder(
        db: AsyncSession, folder_id: str, folder_update: FolderUpdate
    ) -> Optional[Folder]:
        """Update a folder."""
        folder = await DocumentService.get_folder(db, folder_id)
        if not folder:
            return None

        update_data = folder_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                if key == "parent_folder_id":
                    setattr(folder, key, uuid_lib.UUID(value) if value else None)
                elif key == "permission_scope":
                    setattr(folder, key, PermissionScope(value))
                else:
                    setattr(folder, key, value)

        folder.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(folder)
        return folder

    @staticmethod
    async def delete_folder(db: AsyncSession, folder_id: str) -> bool:
        """Delete a folder and all its documents."""
        folder = await DocumentService.get_folder(db, folder_id)
        if not folder:
            return False

        # Delete all documents in this folder (cascade will handle MongoDB content cleanup)
        documents = await db.execute(
            select(Document).where(Document.folder_id == uuid_lib.UUID(folder_id))
        )
        content_collection = get_document_content_collection()
        for doc in documents.scalars():
            # Delete content from MongoDB
            await content_collection.delete_one({"_id": str(doc.content_id)})

        # Delete subfolders recursively
        subfolders = await db.execute(
            select(Folder).where(Folder.parent_folder_id == uuid_lib.UUID(folder_id))
        )
        for subfolder in subfolders.scalars():
            await DocumentService.delete_folder(db, str(subfolder.id))

        # Delete the folder (cascade deletes documents)
        await db.delete(folder)
        await db.commit()
        return True

    @staticmethod
    async def list_folders(
        db: AsyncSession,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        parent_folder_id: Optional[str] = None,
    ) -> List[Folder]:
        """List folders based on filters."""
        query = select(Folder)

        if user_id:
            query = query.where(Folder.user_id == uuid_lib.UUID(user_id))
        if group_id:
            query = query.where(Folder.group_id == uuid_lib.UUID(group_id))
        if parent_folder_id:
            query = query.where(Folder.parent_folder_id == uuid_lib.UUID(parent_folder_id))
        else:
            # If no parent specified, return root folders only
            query = query.where(Folder.parent_folder_id.is_(None))

        result = await db.execute(query)
        return list(result.scalars().all())

    # Document operations

    @staticmethod
    async def create_document(
        db: AsyncSession, document_data: DocumentCreate, user_id: str, permissions: dict
    ) -> Document:
        """
        Create a new document with content in MongoDB.

        Permission-based validation:
        - :own - Can only create for themselves
        - :group - Can create for themselves (documents don't have group ownership)
        - :all - Can create for any user (admin)
        """
        # Verify folder exists
        folder = await DocumentService.get_folder(db, document_data.folder_id)
        if not folder:
            raise ValueError("Folder not found")

        # Determine document owner based on permissions
        # Check if user has :all permission (admin)
        if check_permission(permissions, "sinas.documents.create:all"):
            # Admin can specify any user_id
            doc_user_id = uuid_lib.UUID(document_data.user_id)
        else:
            # Non-admin can only create for themselves
            # Ignore provided user_id and force to authenticated user
            doc_user_id = uuid_lib.UUID(user_id)

        # Generate content_id for MongoDB
        content_id = uuid_lib.uuid4()

        # Create document metadata in PostgreSQL
        document = Document(
            name=document_data.name,
            description=document_data.description,
            filetype=FileType(document_data.filetype),
            source=document_data.source,
            folder_id=uuid_lib.UUID(document_data.folder_id),
            content_id=content_id,
            auto_description_webhook_id=uuid_lib.UUID(document_data.auto_description_webhook_id)
            if document_data.auto_description_webhook_id
            else None,
            created_by=uuid_lib.UUID(user_id),
            user_id=doc_user_id,
        )

        db.add(document)
        await db.commit()
        await db.refresh(document)

        # Store content in MongoDB
        content_collection = get_document_content_collection()
        doc_content = DocumentContent(
            content_id=str(content_id), content=document_data.content, version=1
        )
        await content_collection.insert_one(doc_content.model_dump(by_alias=True))

        # Trigger auto-description generation if webhook is configured
        if document.auto_description_webhook_id:
            await DocumentService.generate_description(db, str(document.id))

        # Trigger auto-tagger if configured for this folder
        await DocumentService._trigger_auto_tagger(
            db, str(document.id), str(document.folder_id), user_id
        )

        return document

    @staticmethod
    async def get_document(db: AsyncSession, document_id: str) -> Optional[Document]:
        """Get a document by ID (metadata only, no content)."""
        result = await db.execute(
            select(Document).where(Document.id == uuid_lib.UUID(document_id))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_document_with_content(
        db: AsyncSession, document_id: str
    ) -> Optional[tuple[Document, str]]:
        """Get a document with its content from MongoDB."""
        document = await DocumentService.get_document(db, document_id)
        if not document:
            return None

        # Get content from MongoDB
        content_collection = get_document_content_collection()
        content_doc = await content_collection.find_one({"_id": str(document.content_id)})

        if not content_doc:
            # Content missing in MongoDB
            return (document, "")

        return (document, content_doc.get("content", ""))

    @staticmethod
    async def update_document(
        db: AsyncSession, document_id: str, document_update: DocumentUpdate,
        user_id: str = None, user_token: str = None
    ) -> Optional[Document]:
        """Update a document."""
        document = await DocumentService.get_document(db, document_id)
        if not document:
            return None

        update_data = document_update.model_dump(exclude_unset=True)

        # Handle content update separately (MongoDB)
        content_updated = False
        if "content" in update_data:
            content = update_data.pop("content")
            content_collection = get_document_content_collection()

            # Increment version
            new_version = document.version + 1

            await content_collection.update_one(
                {"_id": str(document.content_id)},
                {
                    "$set": {
                        "content": content,
                        "version": new_version,
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            document.version = new_version
            content_updated = True

        # Update metadata in PostgreSQL
        for key, value in update_data.items():
            if value is not None:
                if key == "folder_id":
                    # Verify new folder exists
                    folder = await DocumentService.get_folder(db, value)
                    if not folder:
                        raise ValueError("Folder not found")
                    setattr(document, key, uuid_lib.UUID(value))
                elif key == "filetype":
                    setattr(document, key, FileType(value))
                elif key == "auto_description_webhook_id":
                    setattr(document, key, uuid_lib.UUID(value) if value else None)
                else:
                    setattr(document, key, value)

        document.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(document)

        # Trigger auto-description generation if webhook is configured and content changed
        if content_updated and document.auto_description_webhook_id:
            await DocumentService.generate_description(db, document_id)

        # Trigger auto-tagger if content was updated
        if content_updated and user_id:
            await DocumentService._trigger_auto_tagger(
                db, document_id, str(document.folder_id), user_id
            )

        return document

    @staticmethod
    async def delete_document(db: AsyncSession, document_id: str) -> bool:
        """Delete a document and its content."""
        document = await DocumentService.get_document(db, document_id)
        if not document:
            return False

        # Delete content from MongoDB
        content_collection = get_document_content_collection()
        await content_collection.delete_one({"_id": str(document.content_id)})

        # Delete metadata from PostgreSQL
        await db.delete(document)
        await db.commit()
        return True

    @staticmethod
    async def list_documents(
        db: AsyncSession,
        folder_id: Optional[str] = None,
        user_id: Optional[str] = None,
        filetype: Optional[str] = None,
    ) -> List[Document]:
        """List documents based on filters (metadata only)."""
        query = select(Document)

        if folder_id:
            query = query.where(Document.folder_id == uuid_lib.UUID(folder_id))
        if user_id:
            query = query.where(Document.user_id == uuid_lib.UUID(user_id))
        if filetype:
            query = query.where(Document.filetype == FileType(filetype))

        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def generate_description(db: AsyncSession, document_id: str) -> Optional[str]:
        """
        Generate description for a document using configured webhook.
        The webhook function should accept the document content and return a description.
        """
        # Get document with content
        doc_with_content = await DocumentService.get_document_with_content(db, document_id)
        if not doc_with_content:
            return None

        document, content = doc_with_content

        if not document.auto_description_webhook_id:
            return None

        # Get the webhook configuration
        result = await db.execute(
            select(Webhook).where(Webhook.id == document.auto_description_webhook_id)
        )
        webhook = result.scalar_one_or_none()

        if not webhook or not webhook.is_active:
            print(f"Webhook {document.auto_description_webhook_id} not found or inactive")
            return None

        # Prepare input data for the webhook function
        input_data = {
            "document_id": document_id,
            "content": content,
            "name": document.name,
            "filetype": document.filetype.value,
        }

        try:
            # Generate execution ID
            execution_id = str(uuid_lib.uuid4())

            # Execute the webhook's function
            result = await executor.execute_function(
                function_name=webhook.function_name,
                input_data=input_data,
                execution_id=execution_id,
                trigger_type=TriggerType.MANUAL.value,
                trigger_id=str(document.auto_description_webhook_id),
                user_id=str(document.user_id),
            )

            # Extract description from result
            # Assuming the function returns {"description": "..."} or just a string
            description = None
            if isinstance(result, dict) and "description" in result:
                description = result["description"]
            elif isinstance(result, str):
                description = result

            if description:
                # Update document with generated description
                document.description = description
                document.updated_at = datetime.utcnow()
                await db.commit()
                await db.refresh(document)

                return description

        except Exception as e:
            # Log error but don't fail the operation
            print(f"Error generating description for document {document_id}: {e}")
            import traceback

            traceback.print_exc()

        return None

    @staticmethod
    async def _trigger_auto_tagger(
        db: AsyncSession, document_id: str, folder_id: str, user_id: str
    ):
        """
        Trigger auto-tagger for a document if a tagger rule exists for the folder.
        Runs in background - errors are logged but don't fail the document operation.
        """
        try:
            # Import here to avoid circular dependency
            from app.services.tag_service import TagService
            from app.core.auth import create_access_token, get_user_permissions
            from app.models.user import User

            tag_service = TagService(db)

            # Find tagger rule for this folder
            tagger_rule = await tag_service.find_tagger_rule_for_resource(
                resource_type=ResourceType.DOCUMENT,
                folder_id=folder_id
            )

            if not tagger_rule:
                return  # No auto-tagger configured for this folder

            # Get user info to create token
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                logger.error(f"User {user_id} not found for auto-tagger")
                return

            # Get user permissions
            permissions = await get_user_permissions(db, user_id)

            # Create a temporary token for the tagger service call
            token = create_access_token(user_id, user.email, permissions)

            # Run the tagger
            await tag_service.run_tagger(
                user_id=user_id,
                user_token=token,
                tagger_rule_id=str(tagger_rule.id),
                resource_type=ResourceType.DOCUMENT,
                resource_id=document_id
            )

            logger.info(f"Auto-tagger completed for document {document_id}")

        except Exception as e:
            # Log error but don't fail the document operation
            logger.error(f"Error running auto-tagger for document {document_id}: {e}")
            import traceback
            traceback.print_exc()
