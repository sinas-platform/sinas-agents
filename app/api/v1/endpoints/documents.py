"""
Document management API endpoints.

Provides CRUD operations for folders and documents with permission inheritance.
Documents metadata stored in PostgreSQL, content stored in MongoDB.
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user_with_permissions, set_permission_used
from app.core.permissions import check_permission
from app.core.database import get_db
from app.services.document_service import DocumentService
from app.schemas.document import (
    FolderCreate,
    FolderUpdate,
    FolderResponse,
    DocumentCreate,
    DocumentUpdate,
    DocumentResponse,
    DocumentListResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])


# Folder Endpoints


@router.post("/folders", response_model=FolderResponse)
async def create_folder(
    request: Request,
    folder_data: FolderCreate,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
):
    """Create a new folder."""
    user_id, permissions = current_user_data

    # Determine required permission based on owner type
    if folder_data.owner_type == "user":
        required_perm = "sinas.documents.folders.create:own"
    else:  # group
        required_perm = "sinas.documents.folders.create:group"

    if not check_permission(permissions, required_perm):
        set_permission_used(request, required_perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, required_perm, has_perm=True)

    try:
        folder = await DocumentService.create_folder(db, folder_data, user_id, permissions)
        return FolderResponse.model_validate(folder)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/folders/{folder_id}", response_model=FolderResponse)
async def get_folder(
    request: Request,
    folder_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
):
    """Get a folder by ID."""
    user_id, permissions = current_user_data

    # Check read permission
    if not check_permission(permissions, "sinas.documents.folders.read:group"):
        set_permission_used(request, "sinas.documents.folders.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.documents.folders.read:group", has_perm=True)

    folder = await DocumentService.get_folder(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    return FolderResponse.model_validate(folder)


@router.get("/folders", response_model=List[FolderResponse])
async def list_folders(
    request: Request,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    parent_folder_id: Optional[str] = Query(None),
):
    """List folders with optional filters."""
    current_user_id, permissions = current_user_data

    # Check read permission
    if not check_permission(permissions, "sinas.documents.folders.read:group"):
        set_permission_used(request, "sinas.documents.folders.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.documents.folders.read:group", has_perm=True)

    # If filtering by user_id, ensure user can only see their own unless they have :all
    if user_id and user_id != current_user_id:
        if not check_permission(permissions, "sinas.documents.folders.read:all"):
            raise HTTPException(
                status_code=403, detail="Not authorized to view other users' folders"
            )

    folders = await DocumentService.list_folders(db, user_id, group_id, parent_folder_id)
    return [FolderResponse.model_validate(f) for f in folders]


@router.patch("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(
    request: Request,
    folder_id: str,
    folder_update: FolderUpdate,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
):
    """Update a folder."""
    user_id, permissions = current_user_data

    # Get folder to check ownership
    folder = await DocumentService.get_folder(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Check update permission
    if folder.owner_type.value == "user" and str(folder.user_id) == user_id:
        required_perm = "sinas.documents.folders.update:own"
    elif folder.owner_type.value == "group":
        required_perm = "sinas.documents.folders.update:group"
    else:
        required_perm = "sinas.documents.folders.update:all"

    if not check_permission(permissions, required_perm):
        set_permission_used(request, required_perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, required_perm, has_perm=True)

    try:
        updated_folder = await DocumentService.update_folder(db, folder_id, folder_update)
        if not updated_folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        return FolderResponse.model_validate(updated_folder)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/folders/{folder_id}")
async def delete_folder(
    request: Request,
    folder_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
):
    """Delete a folder and all its contents."""
    user_id, permissions = current_user_data

    # Get folder to check ownership
    folder = await DocumentService.get_folder(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Check delete permission
    if folder.owner_type.value == "user" and str(folder.user_id) == user_id:
        required_perm = "sinas.documents.folders.delete:own"
    elif folder.owner_type.value == "group":
        required_perm = "sinas.documents.folders.delete:group"
    else:
        required_perm = "sinas.documents.folders.delete:all"

    if not check_permission(permissions, required_perm):
        set_permission_used(request, required_perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, required_perm, has_perm=True)

    success = await DocumentService.delete_folder(db, folder_id)
    if not success:
        raise HTTPException(status_code=404, detail="Folder not found")

    return {"message": "Folder deleted successfully"}


# Document Endpoints


@router.post("", response_model=DocumentResponse)
async def create_document(
    request: Request,
    document_data: DocumentCreate,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
):
    """Create a new document."""
    user_id, permissions = current_user_data

    # Check create permission
    if document_data.user_id == user_id:
        required_perm = "sinas.documents.create:own"
    else:
        required_perm = "sinas.documents.create:group"

    if not check_permission(permissions, required_perm):
        set_permission_used(request, required_perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, required_perm, has_perm=True)

    try:
        document = await DocumentService.create_document(db, document_data, user_id, permissions)
        # Get content for response
        doc_with_content = await DocumentService.get_document_with_content(db, str(document.id))
        if not doc_with_content:
            raise HTTPException(status_code=500, detail="Failed to retrieve created document")

        doc, content = doc_with_content
        # Build response with content
        return DocumentResponse(
            id=doc.id,
            name=doc.name,
            description=doc.description,
            content=content,
            filetype=doc.filetype,
            source=doc.source,
            folder_id=doc.folder_id,
            content_id=doc.content_id,
            auto_description_webhook_id=doc.auto_description_webhook_id,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            created_by=doc.created_by,
            user_id=doc.user_id,
            version=doc.version
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    request: Request,
    document_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
):
    """Get a document by ID (with content)."""
    user_id, permissions = current_user_data

    # Check read permission
    if not check_permission(permissions, "sinas.documents.read:group"):
        set_permission_used(request, "sinas.documents.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.documents.read:group", has_perm=True)

    doc_with_content = await DocumentService.get_document_with_content(db, document_id)
    if not doc_with_content:
        raise HTTPException(status_code=404, detail="Document not found")

    doc, content = doc_with_content
    # Build response with content
    return DocumentResponse(
        id=doc.id,
        name=doc.name,
        description=doc.description,
        content=content,
        filetype=doc.filetype,
        source=doc.source,
        folder_id=doc.folder_id,
        content_id=doc.content_id,
        auto_description_webhook_id=doc.auto_description_webhook_id,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        created_by=doc.created_by,
        user_id=doc.user_id,
        version=doc.version
    )


@router.get("", response_model=List[DocumentListResponse])
async def list_documents(
    request: Request,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
    folder_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    filetype: Optional[str] = Query(None),
):
    """List documents with optional filters (without content for performance)."""
    current_user_id, permissions = current_user_data

    # Check read permission
    if not check_permission(permissions, "sinas.documents.read:group"):
        set_permission_used(request, "sinas.documents.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.documents.read:group", has_perm=True)

    # If filtering by user_id, ensure user can only see their own unless they have :all
    if user_id and user_id != current_user_id:
        if not check_permission(permissions, "sinas.documents.read:all"):
            raise HTTPException(
                status_code=403, detail="Not authorized to view other users' documents"
            )

    documents = await DocumentService.list_documents(db, folder_id, user_id, filetype)
    return [DocumentListResponse.model_validate(d) for d in documents]


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document(
    request: Request,
    document_id: str,
    document_update: DocumentUpdate,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
):
    """Update a document."""
    user_id, permissions = current_user_data

    # Get document to check ownership
    document = await DocumentService.get_document(db, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check update permission
    if str(document.user_id) == user_id:
        required_perm = "sinas.documents.update:own"
    else:
        required_perm = "sinas.documents.update:group"

    if not check_permission(permissions, required_perm):
        set_permission_used(request, required_perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, required_perm, has_perm=True)

    # Extract token for auto-tagger
    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    try:
        updated_document = await DocumentService.update_document(
            db, document_id, document_update, user_id, token
        )
        if not updated_document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Get content for response
        doc_with_content = await DocumentService.get_document_with_content(db, document_id)
        if not doc_with_content:
            raise HTTPException(status_code=500, detail="Failed to retrieve updated document")

        doc, content = doc_with_content
        # Build response with content
        return DocumentResponse(
            id=doc.id,
            name=doc.name,
            description=doc.description,
            content=content,
            filetype=doc.filetype,
            source=doc.source,
            folder_id=doc.folder_id,
            content_id=doc.content_id,
            auto_description_webhook_id=doc.auto_description_webhook_id,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            created_by=doc.created_by,
            user_id=doc.user_id,
            version=doc.version
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{document_id}")
async def delete_document(
    request: Request,
    document_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document."""
    user_id, permissions = current_user_data

    # Get document to check ownership
    document = await DocumentService.get_document(db, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check delete permission
    if str(document.user_id) == user_id:
        required_perm = "sinas.documents.delete:own"
    else:
        required_perm = "sinas.documents.delete:group"

    if not check_permission(permissions, required_perm):
        set_permission_used(request, required_perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, required_perm, has_perm=True)

    success = await DocumentService.delete_document(db, document_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"message": "Document deleted successfully"}


@router.post("/{document_id}/generate-description")
async def generate_description(
    request: Request,
    document_id: str,
    current_user_data: tuple = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger description generation for a document."""
    user_id, permissions = current_user_data

    # Get document to check ownership and webhook configuration
    document = await DocumentService.get_document(db, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.auto_description_webhook_id:
        raise HTTPException(
            status_code=400, detail="Document does not have auto-description webhook configured"
        )

    # Check permission
    if str(document.user_id) == user_id:
        required_perm = "sinas.documents.generate_description:own"
    else:
        required_perm = "sinas.documents.generate_description:group"

    if not check_permission(permissions, required_perm):
        set_permission_used(request, required_perm, has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, required_perm, has_perm=True)

    try:
        description = await DocumentService.generate_description(db, document_id)
        if description:
            return {"message": "Description generated successfully", "description": description}
        else:
            return {"message": "Failed to generate description"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating description: {str(e)}")
