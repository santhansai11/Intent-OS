"""Maps service: deterministic travel-time calculation."""
from __future__ import annotations

from typing import Any, Dict

from services.base_service import BaseService


class MapsService(BaseService):
    """Mock routing: deterministic travel estimate per destination."""

    name = "maps"
    description = "Route calculation and travel-time estimates (mock)"

    def cap_calculate_route(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Calculate route and travel time to a destination."""
        destination = params.get("destination") or "Unknown destination"
        origin = params.get("origin") or "Current Location"
        # Deterministic pseudo travel time: 15..39 minutes
        travel = 15 + (sum(destination.encode()) % 25)
        return {
            "origin": origin,
            "destination": destination,
            "travel_time_minutes": travel,
            "mode": "walking/campus shuttle",
            "route": f"{origin} -> Main Hall -> {destination}",
        }
