```python
"""
pnl.py - KILLSHOT PnL (Profit and Loss) Calculation Module
Handles real-time PnL calculation and reporting.
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

def calculate_pnl(position: Dict[str, Any], current_price: float) -> Dict[str, Any]:
    """
    Calculate PnL for a specific position.
    
    Args:
        position: Dictionary containing 'entry_price', 'quantity', 'side' (long/short).
        current_price: Current market price.
        
    Returns:
        Dictionary with calculated PnL metrics.
    """
    try:
        entry_price = position.get('entry_price', 0.0)
        quantity = position.get('quantity', 0.0)
        side = position.get('side', 'long')

        if quantity == 0:
            return {"pnl": 0.0, "pnl_percent": 0.0, "status": "no_position"}

        price_diff = current_price - entry_price
        
        if side == "short":
            price_diff = entry_price - current_price

        pnl = price_diff * quantity
        pnl_percent = (price_diff / entry_price) * 100 if entry_price != 0 else 0.0

        return {
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "current_price": current_price,
            "entry_price": entry_price,
            "timestamp": datetime.now().isoformat(),
            "status": "calculated"
        }

    except Exception as e:
        logger.error(f"Error calculating PnL: {str(e)}")
        return {"pnl": 0.0, "error": str(e), "status": "error"}

def aggregate_pnl(positions: List[Dict[str, Any]], current_prices: Dict[str, float]) -> Dict[str, Any]:
    """
    Aggregate PnL across all open positions.
    
    Args:
        positions: List of position dictionaries.
        current_prices: Dict mapping symbol to current price.
        
    Returns:
        Aggregated PnL summary.
    """
    total_pnl = 0.0
    open_positions = 0
    
    for pos in positions:
        symbol = pos.get('symbol')
        if symbol and symbol in current_prices:
            calc_result = calculate_pnl(pos, current_prices[symbol])
            if calc_result.get('status') == 'calculated':
                total_pnl += calc_result.get('pnl', 0.0)
                open_positions += 1
    
    return {
        "total_pnl": total_pnl,
        "open_positions": open_positions,
        "timestamp": datetime.now().isoformat(),
        "status": "aggregated"
    }