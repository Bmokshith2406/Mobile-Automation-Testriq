from __future__ import annotations
import dataclasses
from datetime import datetime, UTC
from typing import Optional, List
from app.models.database import RepairRecord, ExecutionRecord, FailurePattern
from app.core.repositories.base import Repository

class MongoDBRepository(Repository):
    """
    MongoDB implementation of the repository pattern using Motor.
    """
    
    def __init__(self, db):
        self.db = db
        self.repairs_col = db["repair_records"]
        self.executions_col = db["execution_records"]
        self.patterns_col = db["failure_patterns"]
        
    async def save_repair(self, record: RepairRecord) -> str:
        doc = dataclasses.asdict(record)
        doc["_id"] = record.id
        await self.repairs_col.replace_one({"_id": record.id}, doc, upsert=True)
        return record.id
        
    async def get_repair(self, record_id: str) -> Optional[RepairRecord]:
        doc = await self.repairs_col.find_one({"_id": record_id})
        if doc:
            doc.pop("_id", None)
            return RepairRecord(**doc)
        return None
        
    async def get_repairs_by_step(self, step_id: str, limit: int = 100) -> List[RepairRecord]:
        cursor = self.repairs_col.find({"step_id": step_id}).sort("created_at", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(RepairRecord(**doc))
        return results
        
    async def get_recent_repairs(self, limit: int = 100) -> List[RepairRecord]:
        cursor = self.repairs_col.find({}).sort("created_at", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(RepairRecord(**doc))
        return results
        
    async def count_repairs(self, outcome: Optional[str] = None) -> int:
        query = {"outcome": outcome} if outcome else {}
        return await self.repairs_col.count_documents(query)
        
    async def save_execution(self, record: ExecutionRecord) -> str:
        doc = dataclasses.asdict(record)
        doc["_id"] = record.id
        await self.executions_col.replace_one({"_id": record.id}, doc, upsert=True)
        return record.id
        
    async def get_execution(self, record_id: str) -> Optional[ExecutionRecord]:
        doc = await self.executions_col.find_one({"_id": record_id})
        if doc:
            doc.pop("_id", None)
            return ExecutionRecord(**doc)
        return None
        
    async def get_executions_by_run(self, run_id: str) -> List[ExecutionRecord]:
        cursor = self.executions_col.find({"run_id": run_id})
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(ExecutionRecord(**doc))
        return results
        
    async def get_recent_executions(self, limit: int = 100) -> List[ExecutionRecord]:
        cursor = self.executions_col.find({}).sort("created_at", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(ExecutionRecord(**doc))
        return results
        
    async def track_failure_pattern(self, fingerprint: str, error_type: str, error_pattern: str) -> FailurePattern:
        doc = await self.patterns_col.find_one({"fingerprint": fingerprint})
        if doc:
            doc["occurrences"] += 1
            doc["last_seen"] = datetime.now(UTC)
            await self.patterns_col.replace_one({"_id": doc["_id"]}, doc)
            doc.pop("_id", None)
            return FailurePattern(**doc)
        else:
            pattern = FailurePattern(
                fingerprint=fingerprint,
                error_type=error_type,
                error_pattern=error_pattern,
            )
            pattern_doc = dataclasses.asdict(pattern)
            pattern_doc["_id"] = pattern.id
            await self.patterns_col.insert_one(pattern_doc)
            return pattern
            
    async def get_failure_pattern(self, fingerprint: str) -> Optional[FailurePattern]:
        doc = await self.patterns_col.find_one({"fingerprint": fingerprint})
        if doc:
            doc.pop("_id", None)
            return FailurePattern(**doc)
        return None
        
    async def get_top_failure_patterns(self, limit: int = 10) -> List[FailurePattern]:
        cursor = self.patterns_col.find({}).sort("occurrences", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(FailurePattern(**doc))
        return results
        
    async def get_repair_stats(self) -> dict:
        total = await self.repairs_col.count_documents({})
        if total == 0:
            return {"total": 0, "successes": 0, "success_rate": 0.0, "avg_duration_ms": 0.0, "total_tokens": 0}
            
        successes = await self.repairs_col.count_documents({"outcome": "success"})
        
        pipeline = [
            {"$group": {
                "_id": None,
                "avg_duration": {"$avg": "$duration_ms"},
                "total_tokens": {"$sum": "$tokens_used"}
            }}
        ]
        cursor = self.repairs_col.aggregate(pipeline)
        agg_result = await cursor.to_list(length=1)
        
        avg_duration = agg_result[0]["avg_duration"] if agg_result else 0.0
        total_tokens = agg_result[0]["total_tokens"] if agg_result else 0
        
        return {
            "total": total,
            "successes": successes,
            "success_rate": successes / total if total > 0 else 0.0,
            "avg_duration_ms": avg_duration,
            "total_tokens": total_tokens,
        }
        
    async def get_execution_stats(self) -> dict:
        total = await self.executions_col.count_documents({})
        if total == 0:
            return {"total": 0, "passes": 0, "pass_rate": 0.0, "avg_duration_ms": 0.0, "total_repairs_attempted": 0, "total_repairs_successful": 0}
            
        passes = await self.executions_col.count_documents({"status": "passed"})
        
        pipeline = [
            {"$group": {
                "_id": None,
                "avg_duration": {"$avg": "$duration_ms"},
                "total_attempted": {"$sum": "$repairs_attempted"},
                "total_successful": {"$sum": "$repairs_successful"}
            }}
        ]
        cursor = self.executions_col.aggregate(pipeline)
        agg_result = await cursor.to_list(length=1)
        
        avg_duration = agg_result[0]["avg_duration"] if agg_result else 0.0
        total_attempted = agg_result[0]["total_attempted"] if agg_result else 0
        total_successful = agg_result[0]["total_successful"] if agg_result else 0
        
        return {
            "total": total,
            "passes": passes,
            "pass_rate": passes / total if total > 0 else 0.0,
            "avg_duration_ms": avg_duration,
            "total_repairs_attempted": total_attempted,
            "total_repairs_successful": total_successful,
        }

    async def initialize_indexes(self) -> None:
        """
        Creates necessary search and TTL indexes in MongoDB.
        """
        try:
            import logging
            logger = logging.getLogger("database")

            # 1. Search Indexes
            await self.repairs_col.create_index([("request_id", 1)])
            await self.repairs_col.create_index([("step_id", 1), ("created_at", -1)])
            await self.executions_col.create_index([("run_id", 1)])
            await self.patterns_col.create_index([("fingerprint", 1)], unique=True)
            
            # 2. TTL (Time-To-Live) Index to auto-expire records older than 30 days
            await self.repairs_col.create_index("created_at", expireAfterSeconds=2592000)
            await self.executions_col.create_index("created_at", expireAfterSeconds=2592000)
            logger.info("Initialized MongoDB search and TTL indexes successfully")
        except Exception as e:
            import logging
            logging.getLogger("database").warning("Failed to create MongoDB indexes: %s", e)
