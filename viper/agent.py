```python
import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

class AgentException(Exception):
    """Custom exception for agent-specific errors."""
    pass

class ViperAgent:
    """
    Core Viper Agent. Handles execution, error recovery, and status reporting.
    Reports directly to Claude via the Dashboard.
    """
    
    def __init__(self, agent_id: str, config: Dict[str, Any]):
        self.agent_id = agent_id
        self.config = config
        self.status = "idle"
        self.last_error: Optional[str] = None
        self.is_paused = False
        
    def run_loop(self):
        """
        Main execution loop with robust exception handling.
        Prevents unhandled crashes that trigger 'Agent Exception Detected' alerts.
        """
        logger.info(f"Starting Viper Agent loop for {self.agent_id}")
        
        while True:
            try:
                self.status = "running"
                self._execute_task()
                self.status = "idle"
                
            except ConnectionError as e:
                # Critical: Connection error - do not crash
                self._handle_connection_error(e)
                
            except Exception as e:
                # Catch-all for unexpected errors
                self._handle_unexpected_error(e)
            
            # Safety check: If paused due to error, wait before retrying
            if self.is_paused:
                wait_time = self.config.get("pause_retry_interval", 30)
                logger.warning(f"Agent {self.agent_id} paused. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                time.sleep(self.config.get("poll_interval", 5))

    def _execute_task(self):
        """
        Placeholder for actual agent logic. 
        Must be overridden or implemented by subclasses.
        """
        # Simulate work
        logger.debug(f"Executing task for {self.agent_id}")
        # In production, this calls the actual logic
        pass

    def _handle_connection_error(self, error: ConnectionError):
        """
        Graceful degradation for connection errors.
        Updates status and logs without crashing.
        """
        self.status = "error"
        self.is_paused = True
        self.last_error = str(error)
        
        error_msg = f"Connection error in {self.agent_id}: {error}"
        logger.error(error_msg, exc_info=True)
        
        # Report to Dashboard (simulated)
        self._report_status("connection_failed")

    def _handle_unexpected_error(self, error: Exception):
        """
        Handles unexpected exceptions with full traceback logging.
        """
        self.status = "error"
        self.is_paused = True
        self.last_error = str(error)
        
        error_msg = f"Unexpected exception in {self.agent_id}: {error}"
        logger.error(error_msg, exc_info=True)
        
        self._report_status("exception")

    def _report_status(self, state: str):
        """
        Sends status update to the Command Center Dashboard.
        """
        logger.info(f"Reporting status: {state} for {self.agent_id}")
        # Implementation would send JSON to dashboard endpoint
        # dashboard.post({"agent_id": self.agent_id, "status": state, "error": self.last_error})

    def unpause(self):
        """
        Called by brain.py when the underlying issue (e.g., LLM) is resolved.
        """
        if self.is_paused:
            self.is_paused = False
            self.status = "pending"
            self.last_error = None
            logger.info(f"Agent {self.agent_id} unpause successful.")
            return True
        return False

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "is_paused": self.is_paused,
            "last_error": self.last_error,
            "timestamp": datetime.now().isoformat()
        }
```