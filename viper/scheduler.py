```python
import logging
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class TaskScheduler:
    """
    Manages task queues and posting logic.
    Implements auto-approve for dry-run posts to prevent bottlenecks.
    """
    
    def __init__(self, dry_run_mode: bool = True):
        self.queue: List[Dict[str, Any]] = []
        self.dry_run_mode = dry_run_mode
        self.processed_count = 0

    def add_task(self, task: Dict[str, Any]):
        """
        Adds a task to the queue.
        """
        task["created_at"] = datetime.now().isoformat()
        task["status"] = "pending"
        self.queue.append(task)
        logger.info(f"Task added to queue: {task.get('id', 'unknown')}")

    def process_queue(self):
        """
        Processes tasks in the queue.
        If dry_run_mode is True, auto-approves posts to prevent bottlenecks.
        """
        if not self.queue:
            return

        logger.info(f"Processing {len(self.queue)} tasks in queue.")
        
        # Batch approve logic for dry-run mode
        if self.dry_run_mode:
            logger.info("Dry-run mode active. Auto-approving batch.")
            for task in self.queue:
                task["status"] = "approved"
                task["processed_at"] = datetime.now().isoformat()
                self.processed_count += 1
            self.queue = [] # Clear queue after auto-approval
            logger.info(f"Batch approved {self.processed_count} tasks.")
            return

        # Normal processing logic (if not dry-run)
        for task in self.queue:
            if task.get("status") == "pending":
                # Simulate approval check
                task["status"] = "approved"
                task["processed_at"] = datetime.now().isoformat()
                self.processed_count += 1
                logger.debug(f"Task {task.get('id')} approved.")
        
        self.queue = []

    def get_queue_status(self) -> Dict[str, Any]:
        return {
            "queue_size": len(self.queue),
            "processed_count": self.processed_count,
            "dry_run_mode": self.dry_run_mode,
            "queue_items": self.queue
        }

    def clear_queue(self):
        self.queue = []
        logger.info("Queue cleared.")
```