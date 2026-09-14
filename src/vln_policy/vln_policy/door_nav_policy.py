"""Reactive visual DoorNav B1 engineering policy ported from habitat-lab.

Implements observable-only visual navigation:
local RGB observation
  -> deterministic OpenCV doorway grounder
  -> short-horizon IoU visual target tracker
  -> reactive state machine (SEARCH -> TRACK -> APPROACH -> VERIFY -> STOP)
  -> PolicyActionData (linear_velocity, angular_velocity, stop_probability)
"""

from dataclasses import dataclass, field
from enum import Enum
import math
import time
from typing import List, Optional, Tuple
import cv2
import numpy as np

from vln_core.protocol import PolicyActionData, PolicyOutcome


class DoorNavState(str, Enum):
    SEARCH = "SEARCH"
    TRACK = "TRACK"
    APPROACH = "APPROACH"
    VERIFY = "VERIFY"
    STOP = "STOP"
    FAILED = "FAILED"


@dataclass
class DoorCandidate:
    """Bounding box candidate detected by grounder."""
    bbox_xywh: Tuple[int, int, int, int]
    area_ratio: float
    center_x_norm: float  # Normalized horizontal offset from image center [-1.0, 1.0]
    confidence: float


@dataclass
class VisualTargetTrack:
    """Tracked doorway identity across frames."""
    track_id: int
    bbox_xywh: Tuple[int, int, int, int]
    area_ratio: float
    center_x_norm: float
    confidence: float
    missing_steps: int = 0


@dataclass
class ReactiveDoorNavConfig:
    """Tunable parameters for ReactiveDoorNavPolicy."""
    max_search_steps: int = 40
    max_episode_steps: int = 250
    arrival_area_ratio_threshold: float = 0.18
    arrival_center_tolerance_norm: float = 0.15
    arrival_confirm_frames: int = 3
    grounding_confidence_threshold: float = 0.50
    target_lost_tolerance_steps: int = 4
    tracker_match_iou_threshold: float = 0.10
    tracker_confidence_decay: float = 0.80

    # Doorway geometry filters
    grounder_min_area_ratio: float = 0.015
    grounder_max_area_ratio: float = 0.70
    grounder_min_aspect_ratio: float = 1.15  # Height / Width >= 1.15
    grounder_min_height_ratio: float = 0.22  # Height / ImageHeight >= 0.22
    grounder_nms_iou_threshold: float = 0.40
    grounder_max_candidates: int = 5

    # Vehicle motion parameters
    search_angular_velocity: float = 0.40    # rad/s (left rotation to search)
    approach_linear_velocity: float = 0.35   # m/s
    verify_linear_velocity: float = 0.15     # m/s
    track_angular_velocity: float = 0.35     # rad/s (turning towards target)
    model_version: str = "reactive_doornav_b1"


def compute_iou(box_a: Tuple[int, int, int, int], box_b: Tuple[int, int, int, int]) -> float:
    xa1, ya1, wa, ha = box_a
    xa2, ya2 = xa1 + wa, ya1 + ha
    xb1, yb1, wb, hb = box_b
    xb2, yb2 = xb1 + wb, yb1 + hb

    inter_x1 = max(xa1, xb1)
    inter_y1 = max(ya1, yb1)
    inter_x2 = min(xa2, xb2)
    inter_y2 = min(ya2, yb2)

    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = wa * ha
    area_b = wb * hb
    union_area = area_a + area_b - inter_area
    return inter_area / max(1e-6, union_area)


class OpenCVDoorGrounder:
    """Deterministic image-space doorway grounder using contour analysis."""

    def __init__(self, config: ReactiveDoorNavConfig):
        self.config = config

    def detect(self, rgb_image: np.ndarray) -> List[DoorCandidate]:
        h, w = rgb_image.shape[:2]
        img_area = h * w
        if img_area == 0:
            return []

        # Convert to grayscale and enhance edges
        gray = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 40, 140)

        # Close small gaps in contours
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 7))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(closed, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        candidates: List[DoorCandidate] = []

        for cnt in contours:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            area_ratio = (bw * bh) / img_area
            aspect_ratio = bh / max(1, bw)
            height_ratio = bh / h

            if not (self.config.grounder_min_area_ratio <= area_ratio <= self.config.grounder_max_area_ratio):
                continue
            if aspect_ratio < self.config.grounder_min_aspect_ratio:
                continue
            if height_ratio < self.config.grounder_min_height_ratio:
                continue

            center_x_norm = ((bx + bw / 2.0) - (w / 2.0)) / (w / 2.0)
            # Confidence heuristics: larger and taller doorways have higher initial confidence
            confidence = min(1.0, 0.5 + 0.3 * (height_ratio / 0.8) + 0.2 * min(1.0, aspect_ratio / 2.0))

            if confidence >= self.config.grounding_confidence_threshold:
                candidates.append(
                    DoorCandidate(
                        bbox_xywh=(bx, by, bw, bh),
                        area_ratio=area_ratio,
                        center_x_norm=center_x_norm,
                        confidence=confidence,
                    )
                )

        # Non-Maximum Suppression (NMS)
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        kept_candidates: List[DoorCandidate] = []
        for cand in candidates:
            overlap = False
            for kept in kept_candidates:
                if compute_iou(cand.bbox_xywh, kept.bbox_xywh) > self.config.grounder_nms_iou_threshold:
                    overlap = True
                    break
            if not overlap:
                kept_candidates.append(cand)
            if len(kept_candidates) >= self.config.grounder_max_candidates:
                break

        return kept_candidates


class IoUVisualTargetTracker:
    """Tracks the active target doorway across consecutive observations."""

    def __init__(self, config: ReactiveDoorNavConfig):
        self.config = config
        self._active_track: Optional[VisualTargetTrack] = None

    @property
    def active_track(self) -> Optional[VisualTargetTrack]:
        return self._active_track

    def reset(self) -> None:
        self._active_track = None

    def update(self, candidates: List[DoorCandidate]) -> Optional[VisualTargetTrack]:
        if not candidates:
            if self._active_track is not None:
                self._active_track.missing_steps += 1
                self._active_track.confidence *= self.config.tracker_confidence_decay
                if self._active_track.missing_steps > self.config.target_lost_tolerance_steps:
                    self._active_track = None
            return self._active_track

        if self._active_track is None:
            # Pick best candidate to initialize track
            best = candidates[0]
            self._active_track = VisualTargetTrack(
                track_id=1,
                bbox_xywh=best.bbox_xywh,
                area_ratio=best.area_ratio,
                center_x_norm=best.center_x_norm,
                confidence=best.confidence,
                missing_steps=0,
            )
            return self._active_track

        # Match with best candidate via IoU
        best_iou = 0.0
        best_match: Optional[DoorCandidate] = None
        for cand in candidates:
            iou = compute_iou(self._active_track.bbox_xywh, cand.bbox_xywh)
            if iou > best_iou:
                best_iou = iou
                best_match = cand

        if best_match is not None and best_iou >= self.config.tracker_match_iou_threshold:
            self._active_track.bbox_xywh = best_match.bbox_xywh
            self._active_track.area_ratio = best_match.area_ratio
            self._active_track.center_x_norm = best_match.center_x_norm
            self._active_track.confidence = best_match.confidence
            self._active_track.missing_steps = 0
        else:
            self._active_track.missing_steps += 1
            self._active_track.confidence *= self.config.tracker_confidence_decay
            if self._active_track.missing_steps > self.config.target_lost_tolerance_steps:
                self._active_track = None

        return self._active_track


class ReactiveDoorNavPolicy:
    """Full Reactive DoorNav B1 policy composing grounder, tracker, and executor."""

    def __init__(self, config: Optional[ReactiveDoorNavConfig] = None):
        self.config = config or ReactiveDoorNavConfig()
        self.grounder = OpenCVDoorGrounder(self.config)
        self.tracker = IoUVisualTargetTracker(self.config)

        self._current_episode_id: str = "doornav_ep_0"
        self._current_instruction: str = "find and approach doorway"
        self._step_counter: int = 0
        self._search_steps: int = 0
        self._arrival_frames: int = 0
        self._state: DoorNavState = DoorNavState.SEARCH
        self._is_terminated: bool = False

    @property
    def state(self) -> DoorNavState:
        return self._state

    @property
    def episode_id(self) -> str:
        return self._current_episode_id

    @property
    def is_terminated(self) -> bool:
        return self._is_terminated

    def reset(self, episode_id: str, instruction: str = "find and approach doorway") -> None:
        self._current_episode_id = episode_id
        self._current_instruction = instruction
        self._step_counter = 0
        self._search_steps = 0
        self._arrival_frames = 0
        self._state = DoorNavState.SEARCH
        self._is_terminated = False
        self.tracker.reset()

    def predict(self, rgb_image: np.ndarray, obs_stamp_sec: Optional[float] = None) -> PolicyActionData:
        start_mono = time.monotonic()
        self._step_counter += 1
        stamp = obs_stamp_sec if obs_stamp_sec is not None else time.time()

        if self._is_terminated:
            return PolicyActionData(
                header_stamp_sec=stamp,
                frame_id="base_link",
                episode_id=self._current_episode_id,
                sequence_id=self._step_counter,
                linear_velocity=0.0,
                angular_velocity=0.0,
                stop_probability=0.98 if self._state == DoorNavState.STOP else 1.0,
                inference_latency_ms=0.5,
                valid=True,
                model_version=self.config.model_version,
                outcome=(PolicyOutcome.STOP_REQUESTED if self._state == DoorNavState.STOP else PolicyOutcome.FAILED),
                outcome_detail=("stop latched" if self._state == DoorNavState.STOP else "policy already failed"),
            )

        if self._step_counter >= self.config.max_episode_steps:
            self._state = DoorNavState.FAILED
            self._is_terminated = True
            return self._make_action(
                stamp, 0.0, 0.0, 0.0, start_mono,
                outcome=PolicyOutcome.FAILED,
                outcome_detail="maximum policy episode steps exceeded",
            )

        # 1. Detection and tracking
        candidates = self.grounder.detect(rgb_image)
        target = self.tracker.update(candidates)

        # 2. State Machine execution
        if target is None:
            self._arrival_frames = 0
            self._search_steps += 1
            if self._search_steps > self.config.max_search_steps:
                self._state = DoorNavState.FAILED
                self._is_terminated = True
                return self._make_action(
                    stamp, 0.0, 0.0, 0.0, start_mono,
                    outcome=PolicyOutcome.FAILED,
                    outcome_detail="doorway lost beyond search tolerance",
                )

            # SEARCH: Rotate to find doorway
            self._state = DoorNavState.SEARCH
            v = 0.0
            w = self.config.search_angular_velocity  # Turn left
            p_stop = 0.01
            return self._make_action(stamp, v, w, p_stop, start_mono)

        # Target exists: check centering
        self._search_steps = 0
        offset_norm = target.center_x_norm

        if abs(offset_norm) > self.config.arrival_center_tolerance_norm:
            # TRACK: Turn toward target to center it
            self._arrival_frames = 0
            self._state = DoorNavState.TRACK
            v = 0.05
            # Negative sign: in REP-103, left is positive, right is negative
            # If offset_norm < 0 (left of image), turn left (+w)
            # If offset_norm > 0 (right of image), turn right (-w)
            w = -math.copysign(self.config.track_angular_velocity, offset_norm)
            p_stop = 0.02
            return self._make_action(stamp, v, w, p_stop, start_mono)

        # Target is centered: check distance / area
        if target.area_ratio >= self.config.arrival_area_ratio_threshold:
            self._arrival_frames += 1
            if self._arrival_frames >= self.config.arrival_confirm_frames:
                # STOP: Reached doorway with consecutive confirmation
                self._state = DoorNavState.STOP
                self._is_terminated = True
                return self._make_action(
                    stamp, 0.0, 0.0, 0.98, start_mono,
                    outcome=PolicyOutcome.STOP_REQUESTED,
                    outcome_detail="doorway arrival confirmed",
                )

            # VERIFY: Slow final approach while confirming
            self._state = DoorNavState.VERIFY
            v = self.config.verify_linear_velocity
            w = 0.0
            p_stop = 0.50
            return self._make_action(stamp, v, w, p_stop, start_mono)

        # APPROACH: Centered, approach doorway
        self._arrival_frames = 0
        self._state = DoorNavState.APPROACH
        v = self.config.approach_linear_velocity
        w = -offset_norm * 0.2  # Gentle heading adjustment
        p_stop = 0.02
        return self._make_action(stamp, v, w, p_stop, start_mono)

    def _make_action(
        self,
        stamp: float,
        v: float,
        w: float,
        p_stop: float,
        start_mono: float,
        outcome: PolicyOutcome = PolicyOutcome.RUNNING,
        outcome_detail: str = "",
    ) -> PolicyActionData:
        elapsed_ms = (time.monotonic() - start_mono) * 1000.0
        return PolicyActionData(
            header_stamp_sec=stamp,
            frame_id="base_link",
            episode_id=self._current_episode_id,
            sequence_id=self._step_counter,
            linear_velocity=float(v),
            angular_velocity=float(w),
            stop_probability=float(p_stop),
            inference_latency_ms=float(elapsed_ms),
            valid=True,
            model_version=self.config.model_version,
            outcome=outcome,
            outcome_detail=outcome_detail,
        )
