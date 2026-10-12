"""Cross-platform RGB-D camera interfaces.

The RealSense dependency is imported lazily inside the Linux runtime adapter.
Core code and macOS replay do not require pyrealsense2 or numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass(slots=True)
class CameraConfig:
    width: int = 640
    height: int = 480
    fps: int = 30
    serial_number: str | None = None
    expected_model: str = "D455f"


@dataclass(slots=True)
class RGBDFrame:
    rgb: Any
    depth: Any
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class RGBDCamera(Protocol):
    def start(self) -> None:
        ...

    def capture(self) -> RGBDFrame:
        ...

    def stop(self) -> None:
        ...


class ReplayCamera:
    """Camera-like source for macOS development and deterministic tests."""

    def __init__(self, frames: list[RGBDFrame]) -> None:
        self._frames = frames
        self._index = 0
        self._started = False

    def start(self) -> None:
        self._started = True

    def capture(self) -> RGBDFrame:
        if not self._started:
            raise RuntimeError("camera is not started")
        if self._index >= len(self._frames):
            raise StopIteration("replay camera has no more frames")
        frame = self._frames[self._index]
        self._index += 1
        return frame

    def stop(self) -> None:
        self._started = False


class RealSenseD455fCamera:
    """Linux runtime adapter for Intel RealSense D455f.

    This adapter deliberately does not import pyrealsense2 at module import
    time. It raises a clear message if the Linux runtime dependency is absent.
    Frame persistence and conversion to project observations belong to a
    separate recorder layer.
    """

    def __init__(self, config: CameraConfig | None = None) -> None:
        self.config = config or CameraConfig()
        self._pipeline: Any = None
        self._align: Any = None
        self._rs: Any = None

    def start(self) -> None:
        try:
            import pyrealsense2 as rs  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "RealSense runtime is unavailable. Install and verify "
                "pyrealsense2 on the Linux machine before using D455f."
            ) from exc

        self._rs = rs
        self._pipeline = rs.pipeline()
        pipeline_config = rs.config()
        if self.config.serial_number:
            pipeline_config.enable_device(self.config.serial_number)
        pipeline_config.enable_stream(
            rs.stream.color,
            self.config.width,
            self.config.height,
            rs.format.bgr8,
            self.config.fps,
        )
        pipeline_config.enable_stream(
            rs.stream.depth,
            self.config.width,
            self.config.height,
            rs.format.z16,
            self.config.fps,
        )
        profile = self._pipeline.start(pipeline_config)
        self._align = rs.align(rs.stream.color)

        device = profile.get_device()
        product_line = device.get_info(rs.camera_info.product_line)
        device_name = device.get_info(rs.camera_info.name)
        expected_token = self.config.expected_model.lower().replace("f", "")
        if expected_token not in device_name.lower().replace("f", ""):
            self.stop()
            raise RuntimeError(
                f"unexpected RealSense device {device_name!r} "
                f"(product line {product_line!r}); expected {self.config.expected_model!r}"
            )

    def capture(self) -> RGBDFrame:
        if self._pipeline is None or self._align is None:
            raise RuntimeError("camera is not started")
        frames = self._pipeline.wait_for_frames()
        aligned = self._align.process(frames)
        color_frame = aligned.get_color_frame()
        depth_frame = aligned.get_depth_frame()
        if not color_frame or not depth_frame:
            raise RuntimeError("D455f returned an incomplete RGB-D frame")

        try:
            import numpy as np  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "numpy is required by the Linux RealSense adapter to expose frames"
            ) from exc

        return RGBDFrame(
            rgb=np.asanyarray(color_frame.get_data()),
            depth=np.asanyarray(depth_frame.get_data()),
            metadata={
                "camera_model": "Intel RealSense D455f",
                "width": self.config.width,
                "height": self.config.height,
                "fps": self.config.fps,
                "depth_scale_m": self._depth_scale_m(),
            },
        )

    def stop(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
        self._pipeline = None
        self._align = None

    def _depth_scale_m(self) -> float | None:
        if self._pipeline is None or self._rs is None:
            return None
        device = self._pipeline.get_active_profile().get_device()
        sensors = device.query_sensors()
        for sensor in sensors:
            if sensor.is_depth_sensor():
                return float(sensor.get_depth_scale())
        return None
