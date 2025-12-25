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

# Copyright 2025 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the Li cense is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Robot Web Interface wrapper for DIMOS.
Provides a clean interface to the dimensional-interface FastAPI server.
"""

from dimos.web.dimos_interface.api.server import FastAPIServer


class RobotWebInterface(FastAPIServer):
    """Wrapper class for the dimos-interface FastAPI server."""

    def __init__(self, port=5555, text_streams=None, audio_subject=None, robot=None, **streams):
        self.robot = robot
        super().__init__(
            dev_name="Robot Web Interface",
            edge_type="Bidirectional",
            host="0.0.0.0",
            port=port,
            text_streams=text_streams,
            audio_subject=audio_subject,
            **streams,
        )

        if self.robot is not None:
            self.setup_control_routes()

    def setup_control_routes(self):
        """Setup control routes for robot movement."""
        from fastapi import Request
        from fastapi.responses import JSONResponse
        from dimos.msgs.geometry_msgs import Twist, Vector3

        @self.app.post("/control")
        async def control_robot(request: Request):
            """Handle robot control commands from mobile app."""
            try:
                data = await request.json()
                linear_x = data.get("linear_x", 0.0)
                linear_y = data.get("linear_y", 0.0)
                angular_z = data.get("angular_z", 0.0)

                # Scale velocities (adjust these values as needed for your robot)
                max_linear = 0.5  # m/s
                max_angular = 1.0  # rad/s

                vx = linear_x * max_linear
                vy = linear_y * max_linear
                vz = angular_z * max_angular

                # Create Twist message
                twist = Twist()
                twist.linear = Vector3(x=vx, y=vy, z=0.0)
                twist.angular = Vector3(x=0.0, y=0.0, z=vz)

                # Send velocity command to robot
                if hasattr(self.robot, "move"):
                    self.robot.move(twist, duration=0.0)

                return JSONResponse(
                    {
                        "success": True,
                        "velocities": {
                            "linear_x": vx,
                            "linear_y": vy,
                            "angular_z": vz,
                        },
                    }
                )
            except Exception as e:
                return JSONResponse(status_code=500, content={"success": False, "message": str(e)})
