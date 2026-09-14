"""Episode scenario definitions for reproducible VLN experiments."""

import math
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any

@dataclass
class SuccessRegion:
    """Defines a circular region in the 2D plane indicating successful navigation."""
    center_x: float
    center_y: float
    radius: float

    def contains(self, x: float, y: float) -> bool:
        """Check if a point (x, y) lies inside the success region.
        
        Args:
            x: The x-coordinate of the point.
            y: The y-coordinate of the point.
            
        Returns:
            True if the point is inside or on the boundary of the region.
        """
        distance = math.hypot(x - self.center_x, y - self.center_y)
        return distance <= self.radius

@dataclass
class EpisodeScenario:
    """Represents a single Vision-Language Navigation scenario setup."""
    scenario_id: str
    instruction: str
    start_x: float
    start_y: float
    start_yaw: float
    success_region: SuccessRegion
    max_duration_sec: float = 60.0
    max_steps: int = 500
    tags: List[str] = field(default_factory=list)

    def start_pose_tuple(self) -> Tuple[float, float, float]:
        """Returns the start pose as a tuple (x, y, yaw)."""
        return (self.start_x, self.start_y, self.start_yaw)


def parse_scenarios(data: Dict[str, Any]) -> List[EpisodeScenario]:
    """Parses a dictionary representing a scenario collection into objects.
    
    Args:
        data: A dictionary containing a 'scenarios' key with a list of dictionaries.
            
    Returns:
        A list of EpisodeScenario objects.
    """
    scenarios = []
    for s_dict in data.get("scenarios", []):
        success_region_data = s_dict["success_region"]
        success_region = SuccessRegion(
            center_x=float(success_region_data["center_x"]),
            center_y=float(success_region_data["center_y"]),
            radius=float(success_region_data["radius"])
        )
        
        scenario = EpisodeScenario(
            scenario_id=s_dict["scenario_id"],
            instruction=s_dict["instruction"],
            start_x=float(s_dict["start_x"]),
            start_y=float(s_dict["start_y"]),
            start_yaw=float(s_dict["start_yaw"]),
            success_region=success_region,
            max_duration_sec=float(s_dict.get("max_duration_sec", 60.0)),
            max_steps=int(s_dict.get("max_steps", 500)),
            tags=s_dict.get("tags", [])
        )
        scenarios.append(scenario)
    return scenarios

def load_scenarios_from_yaml(path: str) -> List[EpisodeScenario]:
    """Loads a list of EpisodeScenarios from a YAML file.
    
    Args:
        path: Path to the YAML file.
        
    Returns:
        A list of EpisodeScenario objects parsed from the file.
        
    Raises:
        ImportError: If PyYAML is not installed.
        FileNotFoundError: If the file is not found.
    """
    try:
        import yaml
    except ImportError as e:
        raise ImportError("PyYAML is required to load scenarios from YAML files. Install it with `pip install PyYAML`.") from e
        
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        
    if not data:
        return []
        
    return parse_scenarios(data)
