# Copyright 2025-2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Robot-agnostic MuJoCo simulation driver."""

import logging
import math
from typing import Any

from dimos.hardware.manipulators.base import (
    BaseManipulatorDriver,
    StandardMotionComponent,
    StandardServoComponent,
    StandardStatusComponent,
)
from dimos.hardware.manipulators.base.sdk_interface import BaseManipulatorSDK, ManipulatorInfo
from dimos.simulation.manipulators import MujocoSimBackend

logger = logging.getLogger(__name__)


class SimSDKWrapper(BaseManipulatorSDK):
    """SDK wrapper for a generic MuJoCo simulation backend."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.native_sdk: MujocoSimBackend | None = None
        self.dof = 0
        self._connected = False
        self._servos_enabled = False
        self._mode = 0
        self._state = 0
        self._robot = "unknown"

    def connect(self, config: dict[str, Any]) -> bool:
        """Connect to the MuJoCo simulation backend."""
        try:
            robot = config.get("robot")
            if not robot:
                raise ValueError("robot is required for MuJoCo simulation loading")
            self._robot = str(robot)
            config_path = config.get("config_path")
            headless = bool(config.get("headless", False))

            self.logger.info("Connecting to MuJoCo Sim...")
            self.native_sdk = MujocoSimBackend(
                robot=self._robot,
                config_path=config_path,
                headless=headless,
            )
            self.native_sdk.connect()

            if self.native_sdk.connected:
                self._connected = True
                self._servos_enabled = True
                self._state = 0
                self._mode = 0
                self.dof = int(self.native_sdk.num_joints)
                self.logger.info("Successfully connected to MuJoCo Sim", extra={"dof": self.dof})
                return True

            self.logger.error("Failed to connect to MuJoCo Sim")
            return False
        except Exception as exc:
            self.logger.error(f"Sim connection failed: {exc}")
            return False

    def disconnect(self) -> None:
        """Disconnect from simulation."""
        if self.native_sdk:
            try:
                self.native_sdk.disconnect()
            finally:
                self._connected = False
                self.native_sdk = None

    def is_connected(self) -> bool:
        return bool(self._connected and self.native_sdk and self.native_sdk.connected)

    def get_joint_positions(self) -> list[float]:
        return self.native_sdk.joint_positions[: self.dof] if self.native_sdk else []

    def get_joint_velocities(self) -> list[float]:
        return self.native_sdk.joint_velocities[: self.dof] if self.native_sdk else []

    def get_joint_efforts(self) -> list[float]:
        return self.native_sdk.joint_efforts[: self.dof] if self.native_sdk else []

    def set_joint_positions(
        self,
        positions: list[float],
        _velocity: float = 1.0,
        _acceleration: float = 1.0,
        _wait: bool = False,
    ) -> bool:
        _ = _velocity
        _ = _acceleration
        _ = _wait
        if not self._servos_enabled or not self.native_sdk:
            return False
        self._mode = 0
        self.native_sdk.set_joint_position_targets(positions[: self.dof])
        return True

    def set_joint_velocities(self, velocities: list[float]) -> bool:
        if not self._servos_enabled or not self.native_sdk:
            return False
        self._mode = 1
        dt = 1.0 / self.native_sdk.control_frequency
        current = self.native_sdk.joint_positions
        targets = [current[i] + velocities[i] * dt for i in range(min(len(velocities), self.dof))]
        self.native_sdk.set_joint_position_targets(targets)
        return True

    def set_joint_efforts(self, efforts: list[float]) -> bool:
        self.logger.warning("Torque control not supported in MuJoCo Sim bridge")
        _ = efforts
        return False

    def stop_motion(self) -> bool:
        if not self.native_sdk:
            return False
        self.native_sdk.hold_current_position()
        self._state = 0
        return True

    def enable_servos(self) -> bool:
        self._servos_enabled = True
        self._state = 0
        return True

    def disable_servos(self) -> bool:
        self._servos_enabled = False
        return True

    def are_servos_enabled(self) -> bool:
        return self._servos_enabled

    def get_robot_state(self) -> dict[str, Any]:
        velocities = self.native_sdk.joint_velocities[: self.dof] if self.native_sdk else []
        is_moving = any(abs(v) > 1e-4 for v in velocities)
        self._state = 1 if is_moving else 0
        return {
            "state": self._state,
            "mode": self._mode,
            "error_code": 0,
            "is_moving": is_moving,
        }

    def get_error_code(self) -> int:
        return 0

    def get_error_message(self) -> str:
        return ""

    def clear_errors(self) -> bool:
        self._state = 0
        return True

    def emergency_stop(self) -> bool:
        if self.native_sdk:
            self.native_sdk.hold_current_position()
        self._state = 3
        return True

    def get_info(self) -> ManipulatorInfo:
        return ManipulatorInfo(
            vendor="MuJoCo",
            model=self._robot,
            dof=self.dof,
            firmware_version=None,
            serial_number=None,
        )

    def get_joint_limits(self) -> tuple[list[float], list[float]]:
        if not self.native_sdk:
            return ([], [])
        ranges = getattr(self.native_sdk.model, "jnt_range", None)
        if ranges is None or len(ranges) == 0:
            lower = [-math.pi] * self.dof
            upper = [math.pi] * self.dof
            return (lower, upper)
        limit = min(len(ranges), self.dof)
        lower = [float(ranges[i][0]) for i in range(limit)]
        upper = [float(ranges[i][1]) for i in range(limit)]
        if limit < self.dof:
            lower.extend([-math.pi] * (self.dof - limit))
            upper.extend([math.pi] * (self.dof - limit))
        return (lower, upper)

    def get_velocity_limits(self) -> list[float]:
        max_vel_rad = math.radians(180.0)
        return [max_vel_rad] * self.dof

    def get_acceleration_limits(self) -> list[float]:
        max_acc_rad = math.radians(1145.0)
        return [max_acc_rad] * self.dof


class SimDriver(BaseManipulatorDriver):
    """Generic manipulator driver backed by MuJoCo."""

    def __init__(self, **kwargs: Any) -> None:
        config: dict[str, Any] = kwargs.pop("config", {})

        driver_params = [
            "robot",
            "config_path",
            "headless",
        ]
        for param in driver_params:
            if param in kwargs:
                config[param] = kwargs.pop(param)

        logger.info(f"Initializing SimDriver with config: {config}")

        sdk = SimSDKWrapper()
        components = [
            StandardMotionComponent(sdk),
            StandardServoComponent(sdk),
            StandardStatusComponent(sdk),
        ]

        kwargs.pop("sdk", None)
        kwargs.pop("components", None)
        kwargs.pop("name", None)

        super().__init__(
            sdk=sdk,
            components=components,
            config=config,
            name="SimDriver",
            **kwargs,
        )

        logger.info("SimDriver initialized successfully")


def get_blueprint() -> dict[str, Any]:
    return {
        "name": "SimDriver",
        "class": SimDriver,
        "config": {
            "robot": None,
            "config_path": None,
            "headless": False,
        },
        "inputs": {
            "joint_position_command": "JointCommand",
            "joint_velocity_command": "JointCommand",
        },
        "outputs": {
            "joint_state": "JointState",
            "robot_state": "RobotState",
        },
    }


simulation = SimDriver.blueprint

__all__ = [
    "SimDriver",
    "SimSDKWrapper",
    "get_blueprint",
    "simulation",
]
