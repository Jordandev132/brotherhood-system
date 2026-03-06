```python
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class BudgetManager:
    """
    Manages agent budgets and spending limits.
    Provides structured error reporting to prevent crashes.
    """
    
    def __init__(self, initial_budget: float):
        self.budget = initial_budget
        self.spent = 0.0
        self.error_log = []

    def spend(self, amount: float, context: str) -> Optional[Dict[str, Any]]:
        """
        Attempts to spend from the budget.
        Returns structured error object if failed, instead of raising exception.
        """
        if amount < 0:
            error = {
                "type": "invalid_amount",
                "message": "Amount cannot be negative",
                "amount": amount,
                "context": context
            }
            self.error_log.append(error)
            logger.warning(f"Invalid spend attempt: {error}")
            return error

        if self.budget - self.spent < amount:
            error = {
                "type": "insufficient_funds",
                "message": "Budget exceeded",
                "available": self.budget - self.spent,
                "requested": amount,
                "context": context
            }
            self.error_log.append(error)
            logger.warning(f"Insufficient funds: {error}")
            return error

        self.spent += amount
        logger.info(f"Spend successful: {amount} in {context}. Remaining: {self.budget - self.spent}")
        
        return {
            "status": "success",
            "remaining": self.budget - self.spent,
            "context": context
        }

    def get_budget_status(self) -> Dict[str, Any]:
        return {
            "total_budget": self.budget,
            "spent": self.spent,
            "remaining": self.budget - self.spent,
            "error_count": len(self.error_log)
        }

    def reset_budget(self, new_budget: float):
        self.budget = new_budget
        self.spent = 0.0
        self.error_log = []
        logger.info(f"Budget reset to {new_budget}.")

    def get_errors(self) -> list:
        return self.error_log

    def clear_errors(self):
        self.error_log = []
        logger.info("Error log cleared.")
```