```python
"""
agent.py - KILLSHOT Core Agent Controller
Implements robust exception handling, state management, and auto-recovery logic.
"""

import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class KILLSHOTAgent:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.state = "running"  # running, paused, error
        self.retry_count = 0
        self.max_retries = 5
        self.last_error_time: Optional[datetime] = None
        self.recovery_interval = 60  # seconds

    def run_loop(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main execution loop with robust exception handling.
        
        Args:
            task_data: Input data for the task.
            
        Returns:
            Result dictionary or error status.
        """
        while self.state == "running":
            try:
                # Simulate core logic execution
                # In real implementation, this calls anomaly.py and pnl.py
                result = self._execute_core_logic(task_data)
                
                if result.get('status') == 'error':
                    logger.warning(f"Agent {self.agent_id} returned error status: {result}")
                    self._handle_recovery()
                    continue
                
                return result

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Agent {self.agent_id} exception detected: {error_msg}", exc_info=True)
                
                self.state = "paused"
                self.last_error_time = datetime.now()
                
                # Attempt auto-recovery
                self._handle_recovery()
                
                # If recovery fails after max retries, mark as failed
                if self.retry_count >= self.max_retries:
                    logger.critical(f"Agent {self.agent_id} failed permanently after {self.max_retries} retries.")
                    return {"status": "failed", "error": "Max retries exceeded", "agent_id": self.agent_id}
                
                # Wait before retrying
                time.sleep(self.recovery_interval)

        return {"status": "stopped", "agent_id": self.agent_id}

    def _execute_core_logic(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Placeholder for core logic. Imports and calls anomaly/pnl modules.
        Imports are wrapped to avoid crashing the agent on import failures.
        """
        module_errors: Dict[str, str] = {}

        # Defensive imports: anomaly
        try:
            from viper.anomaly import detect_anomalies, validate_data_integrity  # type: ignore
        except Exception as e:
            module_errors['anomaly'] = str(e)
            logger.exception("Failed to import viper.anomaly: %s", e)
            # Provide safe fallbacks
            def validate_data_integrity(_data: Any) -> bool:
                return False  # fail validation so caller can trigger recovery
            def detect_anomalies(_data: Any) -> list:
                return []

        # Defensive imports: pnl
        try:
            from viper.pnl import calculate_pnl, aggregate_pnl  # type: ignore
        except Exception as e:
            module_errors['pnl'] = str(e)
            logger.exception("Failed to import viper.pnl: %s", e)
            # Provide safe fallbacks
            def calculate_pnl(*args, **kwargs) -> Dict[str, Any]:
                return {"pnl": 0.0, "status": "fallback"}
            def aggregate_pnl(*args, **kwargs) -> Dict[str, Any]:
                return {"total_pnl": 0.0, "open_positions": 0, "timestamp": datetime.now().isoformat(), "status": "fallback"}

        # If any import failed, surface a controlled error to trigger recovery in run_loop
        if module_errors:
            return {
                "status": "error",
                "message": "module_import_failed",
                "errors": module_errors,
                "timestamp": datetime.now().isoformat()
            }
        
        # Proceed with normal processing
        data = task_data.get('data', [])
        if not validate_data_integrity(data):
            return {"status": "error", "message": "Invalid data integrity"}
            
        anomalies = detect_anomalies(data)
        # Simulate PnL calculation
        pnl = calculate_pnl({'entry_price': 100, 'quantity': 10, 'side': 'long'}, 105)
        
        return {
            "status": "success",
            "anomalies": anomalies,
            "pnl": pnl,
            "timestamp": datetime.now().isoformat()
        }

    def _handle_recovery(self):
        """
        Implements auto-recovery logic: pause -> wait -> unpause.
        """
        self.retry_count += 1
        
        # Check if we hit max retries
        if self.retry_count > self.max_retries:
            self.state = "failed"
            logger.error(f"Agent {self.agent_id} marked as failed after {self.max_retries} retries.")
            return

        # Log recovery attempt
        logger.info(f"Agent {self.agent_id} initiating recovery attempt #{self.retry_count}")
        
        # Simulate waiting for API to recover or state to stabilize
        # In a real system, this might check a health endpoint
        time.sleep(5) # Short wait for immediate retry logic
        
        # Attempt to unpause
        self.state = "running"
        logger.info(f"Agent {self.agent_id} unpaused successfully.")

    def pause(self):
        """Force pause the agent."""
        self.state = "paused"
        logger.warning(f"Agent {self.agent_id} manually paused.")

    def unpause(self):
        """Force unpause the agent."""
        self.state = "running"
        self.retry_count = 0
        logger.info(f"Agent {self.agent_id} manually unpaused.")

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "state": self.state,
            "retry_count": self.retry_count,
            "last_error_time": self.last_error_time.isoformat() if self.last_error_time else None
        }
```