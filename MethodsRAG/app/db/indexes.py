"""Database indexes and initialization."""

from app.db.mongo import get_methods_collection, get_audit_collection, get_users_collection
from app.core.logging import logger


async def create_indexes():
    """Create all required indexes for collections."""
    try:
        logger.info("Creating database indexes...")
        
        # Methods collection indexes
        methods_coll = get_methods_collection()
        
        # Vector search index (should already exist, but let's verify)
        # This is created manually in MongoDB Atlas
        logger.info("Vector index assumed to exist in MongoDB Atlas")
        
        # Regular indexes for common queries
        await methods_coll.create_index([("method_name", 1)])
        logger.info("Created index on method_name")
        
        await methods_coll.create_index([("CreatedAt", -1)])
        logger.info("Created index on CreatedAt")

        await methods_coll.create_index([("created_at", -1)])
        logger.info("Created index on created_at")
        
        # Compound index for common search patterns
        await methods_coll.create_index([("method_name", 1), ("CreatedAt", -1)])
        logger.info("Created compound index on method_name + CreatedAt")
        
        # Index for deduplication lookups
        await methods_coll.create_index([("method_documentation.summary", "text")])
        logger.info("Created text index on method_documentation.summary")
        
        # Soft delete index
        await methods_coll.create_index([("deleted_at", 1)])
        logger.info("Created index on deleted_at")
        
        # Audit collection indexes
        audit_coll = get_audit_collection()
        
        await audit_coll.create_index([("timestamp", -1)])
        logger.info("Created index on audit timestamp")
        
        await audit_coll.create_index([("user_id", 1), ("timestamp", -1)])
        logger.info("Created compound index on audit user_id + timestamp")

        await audit_coll.create_index([("endpoint", 1), ("timestamp", -1)])
        logger.info("Created compound index on audit endpoint + timestamp")

        await audit_coll.create_index([("action", 1)])
        logger.info("Created index on audit action")
        
        # Users collection indexes
        users_coll = get_users_collection()
        
        await users_coll.create_index([("api_key", 1)], unique=True, sparse=True)
        logger.info("Created unique index on api_key")
        
        await users_coll.create_index([("email", 1)], unique=True, sparse=True)
        logger.info("Created unique index on email")

        await users_coll.create_index([("username", 1)], unique=True, sparse=True)
        logger.info("Created unique index on username")
        
        await users_coll.create_index([("created_at", -1)])
        logger.info("Created index on users created_at")
        
        logger.info("All database indexes created successfully")
        
    except Exception as e:
        logger.warning(f"Error creating indexes: {e}")
        # Don't raise - indexes may already exist
