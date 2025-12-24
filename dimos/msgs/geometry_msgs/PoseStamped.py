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

from __future__ import annotations

import struct
import time
from io import BytesIO
from typing import BinaryIO, TypeAlias

from dimos_lcm.geometry_msgs import PoseStamped as LCMPoseStamped
from dimos_lcm.std_msgs import Header as LCMHeader
from dimos_lcm.std_msgs import Time as LCMTime


try:
    from geometry_msgs.msg import PoseStamped as ROSPoseStamped
except ImportError:
    ROSPoseStamped = None

from plum import dispatch

from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.msgs.geometry_msgs.Quaternion import Quaternion, QuaternionConvertable
from dimos.msgs.geometry_msgs.Transform import Transform
from dimos.msgs.geometry_msgs.Vector3 import Vector3, VectorConvertable
from dimos.types.timestamped import Timestamped

# Types that can be converted to/from Pose
PoseConvertable: TypeAlias = (
    tuple[VectorConvertable, QuaternionConvertable]
    | LCMPoseStamped
    | dict[str, VectorConvertable | QuaternionConvertable]
)


def sec_nsec(ts):
    s = int(ts)
    return [s, int((ts - s) * 1_000_000_000)]


class PoseStamped(Pose, Timestamped):
    msg_name = "geometry_msgs.PoseStamped"
    ts: float
    frame_id: str

    @dispatch
    def __init__(self, ts: float = 0.0, frame_id: str = "", **kwargs) -> None:
        self.frame_id = frame_id
        self.ts = ts if ts != 0 else time.time()
        super().__init__(**kwargs)

    def lcm_encode(self) -> bytes:
        lcm_mgs = LCMPoseStamped()
        lcm_mgs.pose = self
        [lcm_mgs.header.stamp.sec, lcm_mgs.header.stamp.nsec] = sec_nsec(self.ts)
        lcm_mgs.header.frame_id = self.frame_id
        return lcm_mgs.lcm_encode()

    @classmethod
    def lcm_decode(cls, data: bytes | BinaryIO) -> PoseStamped:
        lcm_msg = LCMPoseStamped.lcm_decode(data)
        return cls(
            ts=lcm_msg.header.stamp.sec + (lcm_msg.header.stamp.nsec / 1_000_000_000),
            frame_id=lcm_msg.header.frame_id,
            position=[lcm_msg.pose.position.x, lcm_msg.pose.position.y, lcm_msg.pose.position.z],
            orientation=[
                lcm_msg.pose.orientation.x,
                lcm_msg.pose.orientation.y,
                lcm_msg.pose.orientation.z,
                lcm_msg.pose.orientation.w,
            ],  # noqa: E501,
        )

    def __str__(self) -> str:
        return (
            f"PoseStamped(pos=[{self.x:.3f}, {self.y:.3f}, {self.z:.3f}], "
            f"euler=[{self.roll:.3f}, {self.pitch:.3f}, {self.yaw:.3f}])"
        )

    def __matmul__(self, transform: LCMTransform | Transform) -> Pose:
        return self + transform

    def __add__(self, other: "Pose" | PoseConvertable | LCMTransform | Transform) -> "Pose":
        """Compose two poses or apply a transform (transform composition).

        The operation self + other represents applying transformation 'other'
        in the coordinate frame defined by 'self'. This is equivalent to:
        - First apply transformation 'self' (from world to self's frame)
        - Then apply transformation 'other' (from self's frame to other's frame)

        This matches ROS tf convention where:
        T_world_to_other = T_world_to_self * T_self_to_other

        Args:
            other: The pose or transform to compose with this one

        Returns:
            A new Pose representing the composed transformation

        Example:
            robot_pose = Pose(1, 0, 0)  # Robot at (1,0,0) facing forward
            object_in_robot = Pose(2, 0, 0)  # Object 2m in front of robot
            object_in_world = robot_pose + object_in_robot  # Object at (3,0,0) in world

            # Or with a Transform:
            transform = Transform()
            transform.translation = Vector3(2, 0, 0)
            transform.rotation = Quaternion(0, 0, 0, 1)
            new_pose = pose + transform
        """
        # Handle Transform objects
        if isinstance(other, Transform):
            # Convert Transform to Pose using its translation and rotation
            other_position = Vector3(other.translation)
            other_orientation = Quaternion(other.rotation)

        new_orientation = self.orientation * other_orientation

        # Transform other's position by self's orientation, then add to self's position
        rotated_position = self.orientation.rotate_vector(other_position)
        new_position = self.position + rotated_position

        return PoseStamped(
            self.ts, frame_id=self.frame_id, position=new_position, orientation=new_orientation
        )

    def new_transform_to(self, name: str) -> Transform:
        return self.find_transform(
            PoseStamped(
                frame_id=name,
                position=Vector3(0, 0, 0),
                orientation=Quaternion(0, 0, 0, 1),  # Identity quaternion
            )
        )

    def new_transform_from(self, name: str) -> Transform:
        return self.new_transform_to(name).inverse()

    def find_transform(self, other: PoseStamped) -> Transform:
        inv_orientation = self.orientation.conjugate()

        pos_diff = other.position - self.position

        local_translation = inv_orientation.rotate_vector(pos_diff)

        relative_rotation = inv_orientation * other.orientation

        return Transform(
            child_frame_id=other.frame_id,
            frame_id=self.frame_id,
            translation=local_translation,
            rotation=relative_rotation,
        )

    @classmethod
    def from_ros_msg(cls, ros_msg: ROSPoseStamped) -> "PoseStamped":
        """Create a PoseStamped from a ROS geometry_msgs/PoseStamped message.

        Args:
            ros_msg: ROS PoseStamped message

        Returns:
            PoseStamped instance
        """
        # Convert timestamp from ROS header
        ts = ros_msg.header.stamp.sec + (ros_msg.header.stamp.nanosec / 1_000_000_000)

        # Convert pose
        pose = Pose.from_ros_msg(ros_msg.pose)

        return cls(
            ts=ts,
            frame_id=ros_msg.header.frame_id,
            position=pose.position,
            orientation=pose.orientation,
        )

    def to_ros_msg(self) -> ROSPoseStamped:
        """Convert to a ROS geometry_msgs/PoseStamped message.

        Returns:
            ROS PoseStamped message
        """
        ros_msg = ROSPoseStamped()

        # Set header
        ros_msg.header.frame_id = self.frame_id
        ros_msg.header.stamp.sec = int(self.ts)
        ros_msg.header.stamp.nanosec = int((self.ts - int(self.ts)) * 1_000_000_000)

        # Set pose
        ros_msg.pose = Pose.to_ros_msg(self)

        return ros_msg
