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

from builtin_interfaces.msg import Time as ROSTime
from dimos_lcm.vision_msgs.Detection3DArray import (  # type: ignore[import-untyped]
    Detection3DArray as LCMDetection3DArray,
)
from std_msgs.msg import Header as ROSHeader
from vision_msgs.msg import Detection3DArray as ROSDetection3DArray

from dimos.msgs.vision_msgs.Detection3D import Detection3D


class Detection3DArray(LCMDetection3DArray):  # type: ignore[misc]
    msg_name = "vision_msgs.Detection3DArray"

    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """Initialize with fresh mutable objects to avoid shared state."""
        super().__init__()
        # Create fresh instances to avoid shared mutable state from LCM class defaults
        from dimos_lcm.std_msgs import Header

        self.header = Header()
        self.detections = []

        # Apply any kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_ros_msg(self) -> ROSDetection3DArray:
        """Convert to ROS vision_msgs/Detection3DArray message.

        Returns:
            ROS Detection3DArray message
        """
        ros_msg = ROSDetection3DArray()

        # Set header
        ros_msg.header = ROSHeader()
        ros_msg.header.frame_id = self.header.frame_id
        ros_msg.header.stamp = ROSTime()
        ros_msg.header.stamp.sec = self.header.stamp.sec
        ros_msg.header.stamp.nanosec = self.header.stamp.nsec

        # Convert each detection
        for det in self.detections:
            # Wrap in our Detection3D class if needed to get to_ros_msg
            if not isinstance(det, Detection3D):
                det = Detection3D(
                    header=det.header,
                    results=det.results,
                    bbox=det.bbox,
                    id=getattr(det, "id", ""),
                )
            ros_msg.detections.append(det.to_ros_msg())

        return ros_msg
