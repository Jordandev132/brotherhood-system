```python
"""
anomaly.py - KILLSHOT Anomaly Detection Module
Handles detection of statistical anomalies in trading data.
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

def detect_anomalies(data: List[Dict[str, Any]], threshold: float = 2.0) -> List[Dict[str, Any]]:
    """
    Detect statistical anomalies in the provided data list.
    
    Args:
        data: List of data points (dicts) containing 'value' or similar numeric keys.
        threshold: Standard deviations threshold for anomaly detection.
        
    Returns:
        List of detected anomalies with metadata.
    """
    if not data:
        return []

    try:
        values = [point.get('value', 0) for point in data if isinstance(point.get('value'), (int, float))]
        
        if len(values) < 2:
            return []

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = variance ** 0.5 if variance > 0 else 0.0

        anomalies = []
        for point in data:
            val = point.get('value', 0)
            if std_dev > 0:
                z_score = abs(val - mean) / std_dev
                if z_score > threshold:
                    anomalies.append({
                        "timestamp": point.get('timestamp', datetime.now().isoformat()),
                        "value": val,
                        "z_score": z_score,
                        "type": "statistical_anomaly"
                    })
            else:
                # If std_dev is 0, any non-mean value is an anomaly
                if val != mean:
                    anomalies.append({
                        "timestamp": point.get('timestamp', datetime.now().isoformat()),
                        "value": val,
                        "z_score": float('inf'),
                        "type": "statistical_anomaly"
                    })
        
        return anomalies

    except Exception as e:
        logger.error(f"Error in detect_anomalies: {str(e)}")
        return []

def validate_data_integrity(data: List[Dict[str, Any]]) -> bool:
    """
    Basic validation of data integrity.
    
    Args:
        data: List of data points.
        
    Returns:
        True if data is valid, False otherwise.
    """
    if not isinstance(data, list):
        return False
    
    for item in data:
        if not isinstance(item, dict):
            return False
        if 'value' not in item:
            return False
            
    return True
```