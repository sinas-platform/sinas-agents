"""Schema management for self-managed concepts."""
from datetime import datetime
from typing import List, Optional
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Concept, Property, DataType


class SchemaManager:
    """Manages database schemas for self-managed concepts."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def get_table_name(concept: Concept) -> str:
        """
        Generate table name for a concept.

        Format: ontology_{namespace}_{name}
        """
        return f"ontology_{concept.namespace}_{concept.name}"

    @staticmethod
    def get_pg_type(data_type: DataType) -> str:
        """Map DataType enum to PostgreSQL type."""
        mapping = {
            DataType.STRING: "TEXT",
            DataType.INT: "INTEGER",
            DataType.DECIMAL: "NUMERIC",
            DataType.BOOL: "BOOLEAN",
            DataType.DATETIME: "TIMESTAMP WITH TIME ZONE",
            DataType.JSON: "JSONB",
        }
        return mapping.get(data_type, "TEXT")

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = :table_name
            )
        """)
        result = await self.db.execute(query, {"table_name": table_name})
        return result.scalar()

    async def get_table_columns(self, table_name: str) -> List[str]:
        """Get list of column names for a table."""
        query = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = :table_name
            ORDER BY ordinal_position
        """)
        result = await self.db.execute(query, {"table_name": table_name})
        return [row[0] for row in result.fetchall()]

    async def create_table(self, concept: Concept, properties: List[Property]) -> None:
        """
        Create a new table for a self-managed concept.

        Args:
            concept: The concept to create a table for
            properties: List of properties defining the schema
        """
        table_name = self.get_table_name(concept)

        # Check if table already exists
        if await self.table_exists(table_name):
            raise ValueError(f"Table {table_name} already exists")

        # Build column definitions
        columns = ["id UUID PRIMARY KEY DEFAULT gen_random_uuid()"]

        for prop in properties:
            # Skip 'id' property as it's automatically created
            if prop.name.lower() in ['id', 'created_at', 'updated_at']:
                continue

            pg_type = self.get_pg_type(prop.data_type)
            column_def = f"{prop.name} {pg_type}"

            if prop.is_required:
                column_def += " NOT NULL"

            if prop.default_value:
                column_def += f" DEFAULT {prop.default_value}"

            columns.append(column_def)

        # Add audit columns
        columns.append("created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()")
        columns.append("updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()")

        # Create table
        create_sql = f"""
            CREATE TABLE {table_name} (
                {', '.join(columns)}
            )
        """

        await self.db.execute(text(create_sql))

        # Create indexes for identifier properties
        for prop in properties:
            if prop.is_identifier:
                index_name = f"idx_{table_name}_{prop.name}"
                index_sql = f"CREATE INDEX {index_name} ON {table_name} ({prop.name})"
                await self.db.execute(text(index_sql))

        await self.db.commit()

    async def add_column(
        self,
        concept: Concept,
        property_obj: Property
    ) -> None:
        """
        Add a new column to an existing table.

        Args:
            concept: The concept whose table to modify
            property_obj: The new property to add
        """
        table_name = self.get_table_name(concept)

        # Check if table exists
        if not await self.table_exists(table_name):
            raise ValueError(f"Table {table_name} does not exist")

        # Check if column already exists
        columns = await self.get_table_columns(table_name)
        if property_obj.name in columns:
            raise ValueError(f"Column {property_obj.name} already exists")

        pg_type = self.get_pg_type(property_obj.data_type)
        column_def = f"{property_obj.name} {pg_type}"

        if property_obj.is_required:
            column_def += " NOT NULL"

        if property_obj.default_value:
            column_def += f" DEFAULT {property_obj.default_value}"

        # Add column
        alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {column_def}"
        await self.db.execute(text(alter_sql))

        # Create index if identifier
        if property_obj.is_identifier:
            index_name = f"idx_{table_name}_{property_obj.name}"
            index_sql = f"CREATE INDEX {index_name} ON {table_name} ({property_obj.name})"
            await self.db.execute(text(index_sql))

        await self.db.commit()

    async def migrate_column(
        self,
        concept: Concept,
        old_property: Property,
        new_property: Property
    ) -> None:
        """
        Migrate a column when its type changes.

        Strategy:
        1. Rename old column to old_name_YYYYMMDD_HHMMSS
        2. Create new column with new type
        3. Try to copy/cast data from old to new
        4. Leave old column for manual cleanup

        Args:
            concept: The concept whose table to modify
            old_property: The property before change
            new_property: The property after change
        """
        table_name = self.get_table_name(concept)

        # Check if table exists
        if not await self.table_exists(table_name):
            raise ValueError(f"Table {table_name} does not exist")

        # Generate timestamp suffix
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        old_column_name = f"{old_property.name}_{timestamp}"

        # Rename old column
        rename_sql = f"ALTER TABLE {table_name} RENAME COLUMN {old_property.name} TO {old_column_name}"
        await self.db.execute(text(rename_sql))

        # Add new column
        pg_type = self.get_pg_type(new_property.data_type)
        column_def = f"{new_property.name} {pg_type}"

        if new_property.default_value:
            column_def += f" DEFAULT {new_property.default_value}"

        add_sql = f"ALTER TABLE {table_name} ADD COLUMN {column_def}"
        await self.db.execute(text(add_sql))

        # Try to copy data with type casting
        try:
            copy_sql = f"UPDATE {table_name} SET {new_property.name} = {old_column_name}::{pg_type}"
            await self.db.execute(text(copy_sql))
        except Exception as e:
            # If copy fails, log but continue (old column preserved for manual recovery)
            print(f"Warning: Could not automatically migrate data from {old_column_name} to {new_property.name}: {e}")

        await self.db.commit()

    async def mark_column_deleted(
        self,
        concept: Concept,
        property_obj: Property
    ) -> None:
        """
        Mark a column as deleted by renaming it.

        Strategy:
        1. Rename column to deleted_name_YYYYMMDD_HHMMSS
        2. Leave for manual cleanup

        Args:
            concept: The concept whose table to modify
            property_obj: The property being deleted
        """
        table_name = self.get_table_name(concept)

        # Check if table exists
        if not await self.table_exists(table_name):
            raise ValueError(f"Table {table_name} does not exist")

        # Check if column exists
        columns = await self.get_table_columns(table_name)
        if property_obj.name not in columns:
            raise ValueError(f"Column {property_obj.name} does not exist")

        # Generate timestamp suffix
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        deleted_column_name = f"deleted_{property_obj.name}_{timestamp}"

        # Rename column
        rename_sql = f"ALTER TABLE {table_name} RENAME COLUMN {property_obj.name} TO {deleted_column_name}"
        await self.db.execute(text(rename_sql))

        await self.db.commit()

    async def drop_table(self, concept: Concept) -> None:
        """
        Drop a table for a concept.

        Args:
            concept: The concept whose table to drop
        """
        table_name = self.get_table_name(concept)

        # Check if table exists
        if not await self.table_exists(table_name):
            return  # Already dropped, no-op

        drop_sql = f"DROP TABLE IF EXISTS {table_name} CASCADE"
        await self.db.execute(text(drop_sql))
        await self.db.commit()

    async def cleanup_old_columns(self, concept: Concept) -> List[str]:
        """
        Get list of old/deleted columns that can be manually cleaned up.

        Returns columns matching patterns:
        - {name}_{timestamp}
        - deleted_{name}_{timestamp}

        Args:
            concept: The concept to check

        Returns:
            List of column names that are old/deleted
        """
        table_name = self.get_table_name(concept)

        # Check if table exists
        if not await self.table_exists(table_name):
            return []

        columns = await self.get_table_columns(table_name)

        # Find columns with timestamp suffixes or deleted prefix
        old_columns = []
        for col in columns:
            if col.startswith("deleted_") or "_20" in col:  # Simple heuristic
                old_columns.append(col)

        return old_columns

    async def drop_column(self, concept: Concept, column_name: str) -> None:
        """
        Permanently drop a column (for cleanup).

        Args:
            concept: The concept whose table to modify
            column_name: The column name to drop
        """
        table_name = self.get_table_name(concept)

        # Check if table exists
        if not await self.table_exists(table_name):
            raise ValueError(f"Table {table_name} does not exist")

        # Check if column exists
        columns = await self.get_table_columns(table_name)
        if column_name not in columns:
            raise ValueError(f"Column {column_name} does not exist")

        drop_sql = f"ALTER TABLE {table_name} DROP COLUMN {column_name}"
        await self.db.execute(text(drop_sql))
        await self.db.commit()
