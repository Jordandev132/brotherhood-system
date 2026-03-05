```python
"""
brain.py - KILLSHOT State Manager & Dashboard Integration
Handles state transitions, logging, and integration with the Command Center dashboard.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class StateManager:
    def __init__(self):
        self.agent_states: Dict[str, str] = {}
        self.dashboard_endpoint = "http://localhost:7777/api/alerts" # Placeholder for actual dashboard URL

    def update_agent_state(self, agent_id: str, new_state: str, error_details: Optional[str] = None):
        """
        Update agent state and emit alert to Dashboard if critical.
        
        Args:
            agent_id: Unique identifier for the agent.
            new_state: New state (running, paused, error, failed).
            error_details: Optional error message.
        """
        self.agent_states[agent_id] = new_state
        
        if new_state == "paused":
            logger.warning(f"Agent {agent_id} paused. State updated in Brain.")
            self._emit_dashboard_alert(agent_id, "paused", error_details)
            
        elif new_state == "error":
            logger.error(f"Agent {agent_id} in error state. Critical alert sent to Dashboard.")
            self._emit_dashboard_alert(agent_id, "error", error_details)
            
        elif new_state == "failed":
            logger.critical(f"Agent {agent_id} marked as FAILED. Human intervention required.")
            self._emit_dashboard_alert(agent_id, "failed", error_details)
            
        elif new_state == "running":
            logger.info(f"Agent {agent_id} resumed operation.")
            self._emit_dashboard_alert(agent_id, "running", None)

    def _emit_dashboard_alert(self, agent_id: str, state: str, error_details: Optional[str]):
        """
        Simulate sending alert to Command Center Dashboard.
        In production, this would make an HTTP POST to the dashboard API.
        """
        alert_payload = {
            "timestamp": datetime.now().isoformat(),
            "agent_id": agent_id,
            "state": state,
            "error_details": error_details,
            "priority": "high" if state in ["error", "failed"] else "normal"
        }
        
        # Log the alert payload for visibility
        logger.info(f"Dashboard Alert: {alert_payload}")
        
        # TODO: Implement actual HTTP POST to ~/polymarket-bot/bot/dashboard endpoint
        # requests.post(self.dashboard_endpoint, json=alert_payload)

    def get_all_states(self) -> Dict[str, str]:
        return self.agent_states.copy()

    def transition_paused_to_pending(self, agent_id: str):
        """
        Handle the transition from 'paused' -> 'pending' when recovery succeeds.
        """
        if self.agent_states.get(agent_id) == "paused":
            self.update_agent_state(agent_id, "running")
            logger.info(f"Transitioned {agent_id} from paused to running.")
        else:
            logger.warning(f"Cannot transition {agent_id} from paused to pending. Current state: {self.agent_states.get(agent_id)}")