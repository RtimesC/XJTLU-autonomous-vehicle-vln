"""Unit tests for Reactive DoorNav visual policy."""

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_core")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_policy")))

from vln_core.protocol import validate_policy_action
from vln_policy.door_nav_policy import (
    DoorNavState,
    OpenCVDoorGrounder,
    ReactiveDoorNavConfig,
    ReactiveDoorNavPolicy,
)


def make_blank_image(h: int = 480, w: int = 640) -> np.ndarray:
    return np.full((h, w, 3), 128, dtype=np.uint8)


def make_doorway_image(
    door_x: int,
    door_y: int,
    door_w: int,
    door_h: int,
    h: int = 480,
    w: int = 640,
) -> np.ndarray:
    """Draws a synthetic wall with a tall rectangular doorway."""
    img = np.full((h, w, 3), 180, dtype=np.uint8)
    # Dark doorway interior
    img[door_y : door_y + door_h, door_x : door_x + door_w] = [30, 30, 40]
    # Door frame border
    border_thick = 4
    img[door_y : door_y + border_thick, door_x : door_x + door_w] = [10, 10, 10]
    img[door_y : door_y + door_h, door_x : door_x + border_thick] = [10, 10, 10]
    img[door_y : door_y + door_h, door_x + door_w - border_thick : door_x + door_w] = [10, 10, 10]
    return img


def test_search_mode_when_no_door_visible():
    policy = ReactiveDoorNavPolicy()
    policy.reset("ep_search_test")

    blank = make_blank_image()
    act = policy.predict(blank, obs_stamp_sec=100.0)

    assert policy.state == DoorNavState.SEARCH
    assert act.linear_velocity == 0.0
    assert act.angular_velocity > 0.0  # Rotating left to search
    assert act.stop_probability < 0.05
    assert not policy.is_terminated

    is_valid, err = validate_policy_action(act, expected_episode_id="ep_search_test")
    assert is_valid is True, f"Contract validation failed: {err}"


def test_track_mode_when_door_is_off_center():
    config = ReactiveDoorNavConfig(arrival_center_tolerance_norm=0.15)
    policy = ReactiveDoorNavPolicy(config=config)
    policy.reset("ep_track_test")

    # Place door on the left side of a 640x480 image
    # x=80, w=100, h=220 (h/w=2.2, h/H=0.45, center_x = 130 -> norm = (130-320)/320 = -0.59)
    door_img = make_doorway_image(door_x=80, door_y=120, door_w=100, door_h=220)
    act = policy.predict(door_img, obs_stamp_sec=100.0)

    assert policy.state == DoorNavState.TRACK
    # Door is to the left, robot must turn left (+w in ROS convention)
    assert act.angular_velocity > 0.0
    assert act.stop_probability < 0.05


def test_approach_mode_when_door_is_centered():
    config = ReactiveDoorNavConfig(arrival_area_ratio_threshold=0.18)
    policy = ReactiveDoorNavPolicy(config=config)
    policy.reset("ep_approach_test")

    # Centered door: center_x = 320 -> x = 320 - 50 = 270, w=100, h=220
    # Area = 100*220 = 22000 / (640*480 = 307200) = 0.071 < 0.18 threshold
    door_img = make_doorway_image(door_x=270, door_y=120, door_w=100, door_h=220)
    act = policy.predict(door_img, obs_stamp_sec=100.0)

    assert policy.state == DoorNavState.APPROACH
    assert act.linear_velocity == pytest.approx(0.35)
    assert abs(act.angular_velocity) < 0.1  # Minimal heading correction
    assert act.stop_probability < 0.05


def test_verify_and_stop_consecutive_confirmation():
    config = ReactiveDoorNavConfig(
        arrival_area_ratio_threshold=0.18,
        arrival_confirm_frames=3,
    )
    policy = ReactiveDoorNavPolicy(config=config)
    policy.reset("ep_stop_test")

    # Large centered door: w=260, h=360 -> area = 93600 / 307200 = 0.30 > 0.18
    large_door_img = make_doorway_image(door_x=190, door_y=60, door_w=260, door_h=360)

    # Frame 1: enters VERIFY
    act1 = policy.predict(large_door_img)
    assert policy.state == DoorNavState.VERIFY
    assert act1.linear_velocity == pytest.approx(0.15)
    assert not policy.is_terminated

    # Frame 2: still in VERIFY
    act2 = policy.predict(large_door_img)
    assert policy.state == DoorNavState.VERIFY
    assert not policy.is_terminated

    # Frame 3: 3rd confirmation -> triggers STOP!
    act3 = policy.predict(large_door_img)
    assert policy.state == DoorNavState.STOP
    assert act3.linear_velocity == 0.0
    assert act3.angular_velocity == 0.0
    assert act3.stop_probability >= 0.95
    assert policy.is_terminated is True

    # Frame 4: subsequent step remains locked in STOP
    act4 = policy.predict(large_door_img)
    assert policy.state == DoorNavState.STOP
    assert act4.linear_velocity == 0.0
    assert act4.stop_probability >= 0.95
