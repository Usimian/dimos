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

"""Blueprints for the SO-ARM101 manipulator."""

from pathlib import Path

from dimos.core.blueprints import autoconnect
from dimos.core.transport import LCMTransport
from dimos.hardware.manipulators.lerobot.so_arm101_driver import (
    so_arm101_driver as so_arm101_driver_blueprint,
)
from dimos.manipulation.control import joint_trajectory_controller
from dimos.msgs.sensor_msgs import JointCommand, JointState, RobotState
from dimos.msgs.trajectory_msgs import JointTrajectory


def so_arm101_driver(**config):
    """Create a blueprint for SOArm101Driver with sensible defaults."""
    config.setdefault("serial_port", "/dev/tty.usbmodem5A7A0156371")
    config.setdefault("ip", None)
    config.setdefault("dof", 6)
    config.setdefault("has_gripper", True)
    config.setdefault("has_force_torque", False)
    config.setdefault("state_reader_rate", 100)
    config.setdefault("command_sender_rate", 100)
    config.setdefault("state_publisher_rate", 50)
    config.setdefault("urdf_path", str(Path(__file__).resolve().parent / "so101.urdf"))
    # Keep LeRobot from clamping large deltas unless explicitly configured
    config.setdefault("max_relative_target", None)
    # Default to non-interactive connect; run lerobot-calibrate manually or set True explicitly
    config.setdefault("calibrate", False)

    return so_arm101_driver_blueprint(**config)


so_arm101_servo = so_arm101_driver().transports(
    {
        ("joint_state", JointState): LCMTransport("/lerobot/joint_states", JointState),
        ("robot_state", RobotState): LCMTransport("/lerobot/robot_state", RobotState),
        ("joint_position_command", JointCommand): LCMTransport(
            "/lerobot/joint_position_command", JointCommand
        ),
    }
)


so_arm101_trajectory = autoconnect(
    so_arm101_driver(),
    joint_trajectory_controller(control_frequency=100.0),
).transports(
    {
        ("joint_state", JointState): LCMTransport("/lerobot/joint_states", JointState),
        ("robot_state", RobotState): LCMTransport("/lerobot/robot_state", RobotState),
        ("joint_position_command", JointCommand): LCMTransport(
            "/lerobot/joint_position_command", JointCommand
        ),
        ("trajectory", JointTrajectory): LCMTransport("/lerobot/trajectory", JointTrajectory),
    }
)


__all__ = ["so_arm101_driver", "so_arm101_servo", "so_arm101_trajectory"]
