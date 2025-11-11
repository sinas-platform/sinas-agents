"""
MongoDB connection and database client.
"""
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings


class MongoDB:
    """MongoDB connection manager."""

    def __init__(self):
        self.client: AsyncIOMotorClient | None = None
        self.database = None

    async def connect(self):
        """Connect to MongoDB."""
        self.client = AsyncIOMotorClient(settings.mongodb_url)
        self.database = self.client.sinas
        print(f"Connected to MongoDB at {settings.mongodb_url}")

    async def disconnect(self):
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()
            print("Disconnected from MongoDB")

    def get_collection(self, collection_name: str):
        """Get a collection from the database."""
        if self.database is None:
            raise RuntimeError("MongoDB is not connected")
        return self.database[collection_name]


# Global MongoDB instance
mongodb = MongoDB()


# Collections
def get_document_content_collection():
    """Get the document content collection."""
    return mongodb.get_collection("document_content")
