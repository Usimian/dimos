# Copyright 2025 Dimensional Inc.
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

"""SO-ARM101 SDK wrapper backed by LeRobot's SO101Follower."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Iterable

import lerobot  # type: ignore  # single import to ensure package is present
from lerobot.robots.so101_follower.config_so101_follower import SO101FollowerConfig
from lerobot.robots.so101_follower.so101_follower import SO101Follower
from lerobot.utils.constants import HF_LEROBOT_CALIBRATION, ROBOTS

from dimos.hardware.manipulators.base.sdk_interface import BaseManipulatorSDK, ManipulatorInfo
from .components.kinematics import SOArm101IKSolver


class SOArm101SDKWrapper(BaseManipulatorSDK):
    """Adapter that exposes LeRobot's SO101Follower through the standard SDK interface."""

    DEFAULT_ID = "so_arm101"
    ROBOT_NAME = "so101_follower"
    JOINT_ORDER = [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    ]

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.robot = None
        self._connected = False
        self.use_degrees = True
        self.dof = len(self.JOINT_ORDER)

        # Cached state
        self._positions = [0.0] * self.dof  # radians
        self._velocities = [0.0] * self.dof
        self._efforts = [0.0] * self.dof
        self._servos_enabled = False

        # Limits (updated on connect from calibration if available)
        self.joint_limits_lower = [-math.pi] * self.dof
        self.joint_limits_upper = [math.pi] * self.dof
        self.max_joint_velocity = [2.0] * self.dof
        self.max_joint_acceleration = [5.0] * self.dof
        self._ik_solver: SOArm101IKSolver | None = None
        self._urdf_path: Path | None = None

    # ============= Connection Management =============

    def connect(self, config: dict) -> bool:
        """Connect to the SO-ARM101 controller via LeRobot."""
        port = config.get("serial_port") or config.get("port")
        if not port:
            raise RuntimeError("SO-ARM101 requires a serial port (set serial_port or port).")

        self.use_degrees = bool(config.get("use_degrees", True))
        calibrate_flag = bool(config.get("calibrate", False))
        calibration_dir, calibration_id = self._resolve_calibration_location(config)
        self._urdf_path = Path(config.get("urdf_path", Path(__file__).resolve().parent / "so101.urdf"))
        cfg = SO101FollowerConfig(
            port=port,
            id=calibration_id,
            disable_torque_on_disconnect=bool(config.get("disable_torque_on_disconnect", True)),
            max_relative_target=config.get("max_relative_target"),
            use_degrees=self.use_degrees,
            cameras=config.get("cameras", {}),
            calibration_dir=calibration_dir,
        )

        self.logger.info("Connecting to SO-ARM101 via LeRobot on port %s", port)
        self.robot = SO101Follower(cfg)
        try:
            self.robot.connect(calibrate=calibrate_flag)
        except EOFError as exc:  # noqa: BLE001
            raise RuntimeError(
                "Calibration requires interactive input. Run `lerobot-calibrate` manually or set "
                "calibrate=False in the driver config once calibration is written to motors."
            ) from exc
        if not calibrate_flag and not self.robot.is_calibrated:
            raise RuntimeError(
                "SO-ARM101 is not calibrated. "
                f"Expected calibration file id='{self.robot.id}' at '{self.robot.calibration_fpath}'. "
                "Run `lerobot-calibrate` once (matching id and calibration_dir) or set calibrate=True "
                "to perform interactive calibration."
            )
        try:
            self.robot.bus.enable_torque()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to enable torque on connect: %s", exc)
        self._connected = True
        self._servos_enabled = True

        # If we are skipping interactive calibration but have a calibration file,
        # proactively push it to the motors so LeRobot reports calibrated.
        if not calibrate_flag and getattr(self.robot, "calibration", None):
            try:
                self.logger.info("Applying calibration from %s to motors", self.robot.calibration_fpath)
                self.robot.bus.disable_torque()
                self.robot.bus.write_calibration(self.robot.calibration)
                self.robot.bus.enable_torque()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Failed to apply calibration automatically: %s", exc)

        if not calibrate_flag and not self.robot.is_calibrated:
            raise RuntimeError(
                "SO-ARM101 is not calibrated. "
                f"Expected calibration file id='{self.robot.id}' at '{self.robot.calibration_fpath}' "
                "and matching motor limits. Run `lerobot-calibrate` once (matching id and "
                "calibration_dir), set calibrate=True to perform interactive calibration, or ensure "
                "the cached calibration is written to the motors."
            )

        self._update_limits_from_calibration()
        return True

    def disconnect(self) -> None:
        if self.robot:
            try:
                self.robot.disconnect()
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("SO-ARM101 disconnect warning: %s", exc)
        self._connected = False
        self.robot = None

    def is_connected(self) -> bool:
        return self._connected

    # ============= Joint State Query =============

    def get_joint_positions(self) -> list[float]:
        robot = self._require_robot()
        try:
            obs = robot.get_observation()
            values = [obs.get(f"{name}.pos", 0.0) for name in self.JOINT_ORDER]
            if self.use_degrees:
                radians = [math.radians(v) for v in values]
            else:
                radians = [
                    self._normalized_to_rad(v, is_gripper=(i == 5)) for i, v in enumerate(values)
                ]
            self._positions = radians[: self.dof]
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("SO-ARM101 get_observation failed: %s", exc)
        return list(self._positions)

    def get_joint_velocities(self) -> list[float]:
        return list(self._velocities)

    def get_joint_efforts(self) -> list[float]:
        return list(self._efforts)

    # ============= Joint Motion Control =============

    def set_joint_positions(
        self,
        positions: Iterable[float],
        velocity: float = 1.0,
        acceleration: float = 1.0,
        wait: bool = False,
    ) -> bool:
        _ = velocity, acceleration, wait  # Not supported by SO101Follower
        robot = self._require_robot()

        if not self._servos_enabled:
            self.logger.warning("Servos disabled; ignoring position command")
            return False

        positions = list(positions)[: self.dof]
        try:
            if self.use_degrees:
                values = [math.degrees(p) for p in positions]
            else:
                values = [
                    self._rad_to_normalized(p, is_gripper=(i == 5))
                    for i, p in enumerate(positions)
                ]

            action = {f"{name}.pos": values[i] for i, name in enumerate(self.JOINT_ORDER)}
            self.logger.debug("SO-ARM101 sending action: %s", action)
            sent = robot.send_action(action)
            applied = [sent.get(f"{name}.pos", values[i]) for i, name in enumerate(self.JOINT_ORDER)]
            self._positions = (
                [math.radians(v) for v in applied]
                if self.use_degrees
                else [self._normalized_to_rad(v, is_gripper=(i == 5)) for i, v in enumerate(applied)]
            )
            self._velocities = [0.0] * self.dof
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.error("SO-ARM101 set_joint_positions failed: %s", exc)
            return False

    def set_joint_velocities(self, velocities: Iterable[float]) -> bool:
        _ = velocities
        self.logger.warning("Velocity control not supported by SO-ARM101 SDK; ignoring command")
        return False

    def set_joint_efforts(self, efforts: Iterable[float]) -> bool:
        _ = efforts
        self.logger.warning("Effort control not supported by SO-ARM101 SDK")
        return False

    def stop_motion(self) -> bool:
        try:
            return self.set_joint_positions(self._positions, wait=False)
        except Exception:  # noqa: BLE001
            return False

    # ============= Servo Control =============

    def enable_servos(self) -> bool:
        robot = self._require_robot()
        try:
            robot.bus.enable_torque()
            self._servos_enabled = True
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to enable torque: %s", exc)
            return False

    def disable_servos(self) -> bool:
        if not self.robot:
            return False
        try:
            self.robot.bus.disable_torque()
            self._servos_enabled = False
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to disable torque: %s", exc)
            return False

    def are_servos_enabled(self) -> bool:
        return self._servos_enabled

    # ============= System State =============

    def get_robot_state(self) -> dict:
        return {
            "state": 0 if self._servos_enabled else 1,
            "mode": 0,
            "error_code": 0 if self._servos_enabled else 1,
            "warn_code": 0,
            "is_moving": any(abs(v) > 1e-4 for v in self._velocities),
            "cmd_num": 0,
        }

    def get_error_code(self) -> int:
        return 0

    def get_error_message(self) -> str:
        return ""

    def clear_errors(self) -> bool:
        return True

    def emergency_stop(self) -> bool:
        self._servos_enabled = False
        self._velocities = [0.0] * self.dof
        return True

    # ============= Information =============

    def get_info(self) -> ManipulatorInfo:
        return ManipulatorInfo(
            vendor="LeRobot",
            model="SO-ARM101 Follower",
            dof=self.dof,
        )

    def get_joint_limits(self) -> tuple[list[float], list[float]]:
        return (list(self.joint_limits_lower), list(self.joint_limits_upper))

    def get_velocity_limits(self) -> list[float]:
        return list(self.max_joint_velocity)

    def get_acceleration_limits(self) -> list[float]:
        return list(self.max_joint_acceleration)

    # ============= Cartesian Control (IK-backed) =============

    def get_cartesian_position(self) -> dict | None:
        if not self._ensure_ik_solver():
            return None
        # Use cached joint state to approximate pose
        if any(abs(v) > 1e-6 for v in self._positions):
            try:
                pos, quat = self._ik_solver.get_end_effector_pose(self._positions)  # type: ignore[union-attr]
                # Convert quaternion to roll/pitch/yaw
                try:
                    from scipy.spatial.transform import Rotation as R  # type: ignore[import]

                    rpy = R.from_quat(quat).as_euler("xyz").tolist()
                except Exception:  # noqa: BLE001
                    rpy = [0.0, 0.0, 0.0]
                return {"x": pos[0], "y": pos[1], "z": pos[2], "roll": rpy[0], "pitch": rpy[1], "yaw": rpy[2]}
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("FK lookup failed: %s", exc)
        return None

    def set_cartesian_position(
        self, pose: dict, velocity: float = 1.0, acceleration: float = 1.0, wait: bool = False
    ) -> bool:
        """Solve IK for the requested pose and send joint targets."""
        if not self._ensure_ik_solver():
            self.logger.error("Cartesian control requested but IK solver unavailable")
            return False
        try:
            from scipy.spatial.transform import Rotation as R  # type: ignore[import]
            import numpy as np  # type: ignore[import]
        except Exception as exc:  # noqa: BLE001
            self.logger.error("IK dependencies missing (numpy/scipy/pinocchio): %s", exc)
            return False

        try:
            target_pos = np.array([pose["x"], pose["y"], pose["z"]], dtype=float)
            rpy = [pose.get("roll", 0.0), pose.get("pitch", 0.0), pose.get("yaw", 0.0)]
            quat = R.from_euler("xyz", rpy).as_quat()  # xyzw

            current = self.get_joint_positions()
            result = self._ik_solver.solve_ik(  # type: ignore[union-attr]
                target_position=target_pos,
                target_orientation=np.array(quat, dtype=float),
                current_joints=np.array(current, dtype=float),
                position_only=False,
            )
            success, joints = result
            if not success:
                self.logger.warning("IK solve failed for pose %s", pose)
                return False
            return self.set_joint_positions(joints, velocity=velocity, acceleration=acceleration, wait=wait)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("set_cartesian_position failed: %s", exc)
            return False

    # ============= Helpers =============

    def _require_robot(self):
        if not self.robot or not self._connected:
            raise RuntimeError("SO-ARM101 is not connected.")
        return self.robot

    def _update_limits_from_calibration(self) -> None:
        calib = getattr(self.robot, "calibration", None) if self.robot else None
        if not calib:
            return
        lowers: list[float] = []
        uppers: list[float] = []
        for idx, name in enumerate(self.JOINT_ORDER):
            cal = calib.get(name)
            if not cal:
                return
            if self.use_degrees:
                lowers.append(math.radians(cal.range_min))
                uppers.append(math.radians(cal.range_max))
            else:
                lowers.append(self._normalized_to_rad(cal.range_min, is_gripper=(idx == 5)))
                uppers.append(self._normalized_to_rad(cal.range_max, is_gripper=(idx == 5)))
        if len(lowers) == self.dof:
            self.joint_limits_lower = lowers
            self.joint_limits_upper = uppers

    @staticmethod
    def _normalized_to_rad(value: float, *, is_gripper: bool = False) -> float:
        if is_gripper:
            return (max(0.0, min(100.0, value)) / 100.0) * math.pi
        return (max(-100.0, min(100.0, value)) / 100.0) * math.pi

    @staticmethod
    def _rad_to_normalized(value: float, *, is_gripper: bool = False) -> float:
        if is_gripper:
            return max(0.0, min(100.0, (value / math.pi) * 100.0))
        return max(-100.0, min(100.0, (value / math.pi) * 100.0))

    def _resolve_calibration_location(self, config: dict) -> tuple[Path, str]:
        """Normalize calibration inputs and pick an existing calibration file if present.

        Users sometimes pass a full calibration file path or an id with a '.json'
        suffix, which results in a double extension when LeRobot appends '.json'.
        This helper resolves those cases and prefers an existing calibration file
        in the expected directory when available.
        """

        calibration_dir_raw = config.get("calibration_dir")
        calibration_dir = (
            Path(calibration_dir_raw).expanduser() if calibration_dir_raw is not None else None
        )
        if calibration_dir and calibration_dir.is_file():
            return calibration_dir.parent, calibration_dir.stem

        calibration_id = str(config.get("id", self.DEFAULT_ID))
        if calibration_id.lower().endswith(".json"):
            calibration_id = Path(calibration_id).stem

        base_dir = calibration_dir or Path(HF_LEROBOT_CALIBRATION) / ROBOTS / self.ROBOT_NAME

        expected = base_dir / f"{calibration_id}.json"
        if not expected.is_file():
            double_ext = base_dir / f"{calibration_id}.json.json"
            if double_ext.is_file():
                self.logger.warning(
                    "Calibration file has a double '.json' extension at %s; using it.",
                    double_ext,
                )
                return double_ext.parent, double_ext.stem

            fallback = next(iter(sorted(base_dir.glob("*.json"))), None)
            if fallback:
                self.logger.warning(
                    "Calibration file %s not found; falling back to %s. "
                    "Update the driver id to '%s' or rename the file to match.",
                    expected,
                    fallback,
                    fallback.stem,
                )
                return fallback.parent, fallback.stem

        return base_dir, calibration_id

    def _ensure_ik_solver(self) -> bool:
        if self._ik_solver is not None:
            return True
        if self._urdf_path is None:
            self.logger.error("No URDF path provided for IK initialization")
            return False
        try:
            self._ik_solver = SOArm101IKSolver(str(self._urdf_path))
            self.logger.info("Initialized IK solver from %s", self._urdf_path)
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Failed to initialize IK solver: %s", exc)
            self._ik_solver = None
            return False
