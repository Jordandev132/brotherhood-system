```python
import logging
from typing import Optional, Dict, Any
import math

logger = logging.getLogger(__name__)

class PnLCalculator:
    """
    Calculates Profit and Loss.
    Handles missing data gracefully to prevent crashes.
    """
    
    def __init__(self):
        self.last_pnl = 0.0

    def calculate_pnl(self, data: Dict[str, Any]) -> Optional[float]:
        """
        Calculates PnL from trade data.
        Returns None if data is insufficient, preventing unhandled exceptions.
        """
        if not data:
            logger.warning("No data provided for PnL calculation.")
            return None

        try:
            entry_price = data.get("entry_price")
            exit_price = data.get("exit_price")
            quantity = data.get("quantity")
            
            # Validate required fields
            if entry_price is None or exit_price is None or quantity is None:
                logger.warning("Missing required fields for PnL calculation.")
                return None

            # Handle potential NaN or Inf values
            if math.isnan(entry_price) or math.isnan(exit_price) or math.isnan(quantity):
                logger.warning("NaN values detected in PnL calculation.")
                return None

            # Calculate PnL
            pnl = (exit_price - entry_price) * quantity
            
            # Update state
            self.last_pnl = pnl
            
            logger.debug(f"PnL calculated: {pnl}")
            return pnl

        except Exception as e:
            # Catch calculation errors
            logger.error(f"Error calculating PnL: {e}", exc_info=True)
            return None

    def get_last_pnl(self) -> Optional[float]:
        return self.last_pnl

    def reset(self):
        self.last_pnl = 0.0
        logger.info("PnL calculator reset.")
```