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

"""SO-ARM101 driver using the generalized component-based architecture."""

from __future__ import annotations

import logging
from pathlib import Path

from dimos.hardware.manipulators.base import (
    BaseManipulatorDriver,
    StandardMotionComponent,
    StandardServoComponent,
    StandardStatusComponent,
)

from .components import KinematicsComponent
from .so_arm101_wrapper import SOArm101SDKWrapper

logger = logging.getLogger(__name__)


class SOArm101Driver(BaseManipulatorDriver):
    """SO-ARM101 driver assembled from standard components.

    The heavy lifting is handled by the base driver and standard components.
    This class wires them together with the SO-ARM101 SDK wrapper.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the SO-ARM101 driver.

        Args:
            *args, **kwargs: Arguments for Module initialization.
                Driver configuration can be passed via 'config' keyword arg:
                - serial_port: Serial device for the controller (e.g., '/dev/ttyUSB0')
                - ip: Optional controller IP if using Ethernet
                - dof: Degrees of freedom (default 6)
                - has_gripper: Whether a gripper is attached
                - has_force_torque: Whether an F/T sensor is present
                - urdf_path: Path to SO-ARM101 URDF for IK/FK
                - state_reader_rate: State reading rate (Hz)
                - command_sender_rate: Command sending rate (Hz)
                - state_publisher_rate: State publishing rate (Hz)
        """
        config = kwargs.pop("config", {})

        driver_params = [
            "serial_port",
            "ip",
            "dof",
            "has_gripper",
            "has_force_torque",
            "urdf_path",
            "state_reader_rate",
            "command_sender_rate",
            "state_publisher_rate",
            "max_relative_target",
            "calibrate",
        ]
        for param in driver_params:
            if param in kwargs:
                config[param] = kwargs.pop(param)

        logger.info(f"Initializing SOArm101Driver with config: {config}")

        sdk = SOArm101SDKWrapper()

        components = [
            StandardMotionComponent(sdk),
            StandardServoComponent(sdk),
            StandardStatusComponent(sdk),
            KinematicsComponent(config.get("urdf_path")),
        ]

        super().__init__(
            sdk=sdk, components=components, config=config, name="SOArm101Driver", *args, **kwargs
        )

        logger.info("SOArm101Driver initialized successfully")


def get_blueprint():
    """Get the blueprint configuration for the SO-ARM101 driver."""
    return {
        "name": "SOArm101Driver",
        "class": SOArm101Driver,
        "config": {
            "serial_port": "/dev/tty.usbmodem5A7A0156371",
            "ip": None,
            "dof": 6,
            "has_gripper": False,
            "has_force_torque": False,
            "urdf_path": str(Path(__file__).resolve().parent / "so101.urdf"),
            "state_reader_rate": 100,
            "command_sender_rate": 100,
            "state_publisher_rate": 50,
            "calibrate": False,
        },
        "inputs": {
            "joint_position_command": "JointCommand",
            "joint_velocity_command": "JointCommand",
        },
        "outputs": {
            "joint_state": "JointState",
            "robot_state": "RobotState",
        },
        "rpc_methods": [
            # Motion control
            "move_joint",
            "stop_motion",
            "get_joint_state",
            "get_joint_limits",
            "move_cartesian",
            "get_cartesian_state",
            "execute_trajectory",
            "stop_trajectory",
            # Servo control
            "enable_servo",
            "disable_servo",
            "toggle_servo",
            "get_servo_state",
            "emergency_stop",
            "reset_emergency_stop",
            "set_control_mode",
            "get_control_mode",
            "clear_errors",
            "reset_fault",
            "home_robot",
            "brake_release",
            "brake_engage",
            # Status monitoring
            "get_robot_state",
            "get_system_info",
            "get_capabilities",
            "get_error_state",
            "get_health_metrics",
            "get_statistics",
            "check_connection",
            "get_force_torque",
            "zero_force_torque",
            "get_digital_inputs",
            "set_digital_outputs",
            "get_analog_inputs",
            "get_gripper_state",
        ],
    }


# Expose blueprint for declarative composition (compatible with dimos framework)
so_arm101_driver = SOArm101Driver.blueprint
