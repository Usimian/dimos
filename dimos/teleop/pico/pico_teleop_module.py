#!/usr/bin/env python3
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

"""
Pico Teleoperation Module — Raw Data Logger.

Subscribes to ALL VR controller data from the Pico WebXR client via the Deno
bridge and logs everything. No outputs, no processing — just print what we get.

The Pico HTML client sends data on these LCM topics:
    /vr_left_pose, /vr_right_pose     — PoseStamped (controller 6DOF)
    /vr_left_joy, /vr_right_joy       — Joy (axes + buttons, raw gamepad)
    /vr_other_N_pose, /vr_other_N_joy — Any non-hand input sources (body trackers, etc.)
"""

from dataclasses import dataclass
from pathlib import Path
import shutil
import signal
import subprocess
import threading
from typing import Any

from reactivex.disposable import Disposable

from dimos.core import In, Module, rpc
from dimos.core.module import ModuleConfig
from dimos.msgs.geometry_msgs import PoseStamped
from dimos.msgs.sensor_msgs import Joy
from dimos.teleop.utils.teleop_transforms import webxr_to_robot
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


@dataclass
class PicoTeleopConfig(ModuleConfig):
    """Configuration for Pico Teleoperation Module."""

    log_interval: float = 1.0  # Seconds between periodic raw data dumps


class PicoTeleopModule(Module[PicoTeleopConfig]):
    """Pico Teleoperation Module — raw data logger.

    Subscribes to all VR streams and logs everything raw.
    No outputs, no engage logic, no processing.
    """

    default_config = PicoTeleopConfig

    # Inputs from Deno bridge
    vr_left_pose: In[PoseStamped]
    vr_right_pose: In[PoseStamped]
    vr_left_joy: In[Joy]
    vr_right_joy: In[Joy]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self._current_poses: dict[str, PoseStamped | None] = {}
        self._last_joy: dict[str, Joy | None] = {}
        self._lock = threading.RLock()

        # Track what we've seen (for one-time first-message logging)
        self._seen_joy: set[str] = set()
        self._seen_pose: set[str] = set()

        # Periodic log thread
        self._log_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Deno bridge server
        self._server_process: subprocess.Popen[bytes] | None = None
        self._server_script = Path(__file__).parent / "web" / "teleop_server.ts"

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    @rpc
    def start(self) -> None:
        super().start()

        input_streams = {
            "vr_left_pose": (self.vr_left_pose, lambda msg: self._on_pose("left", msg)),
            "vr_right_pose": (self.vr_right_pose, lambda msg: self._on_pose("right", msg)),
            "vr_left_joy": (self.vr_left_joy, lambda msg: self._on_joy("left", msg)),
            "vr_right_joy": (self.vr_right_joy, lambda msg: self._on_joy("right", msg)),
        }
        connected = []
        for name, (stream, handler) in input_streams.items():
            if not (stream and stream.transport):  # type: ignore[attr-defined]
                logger.warning(f"Stream '{name}' has no transport — skipping")
                continue
            self._disposables.add(Disposable(stream.subscribe(handler)))  # type: ignore[attr-defined]
            connected.append(name)

        if connected:
            logger.info(f"Subscribed to: {', '.join(connected)}")

        self._start_server()
        self._start_log_loop()
        logger.info("Pico Teleoperation Module started (raw data logger)")

    @rpc
    def stop(self) -> None:
        self._stop_log_loop()
        self._stop_server()
        super().stop()

    # -------------------------------------------------------------------------
    # Callbacks — just store + log first occurrence
    # -------------------------------------------------------------------------

    def _on_pose(self, source: str, pose_stamped: PoseStamped) -> None:
        """Store raw pose. Log first occurrence per source."""
        # Also try robot-frame transform for left/right
        if source in ("left", "right"):
            robot_pose = webxr_to_robot(pose_stamped, is_left_controller=(source == "left"))
        else:
            robot_pose = pose_stamped

        with self._lock:
            self._current_poses[source] = robot_pose

            if source not in self._seen_pose:
                self._seen_pose.add(source)
                p = robot_pose.position
                o = robot_pose.orientation
                fid = pose_stamped.frame_id or "?"
                logger.info(
                    f"[PICO {source}] First pose (frame_id={fid}): "
                    f"pos=({p.x:.4f}, {p.y:.4f}, {p.z:.4f}) "
                    f"rot=({o.x:.4f}, {o.y:.4f}, {o.z:.4f}, {o.w:.4f})"
                )

    def _on_joy(self, source: str, joy: Joy) -> None:
        """Store raw Joy. Log full dump on first occurrence per source."""
        axes = joy.axes or []
        buttons = joy.buttons or []
        frame_id = joy.frame_id or "?"

        with self._lock:
            self._last_joy[source] = joy

            if source not in self._seen_joy:
                self._seen_joy.add(source)
                logger.info(
                    f"[PICO {source}] First Joy (frame_id={frame_id}): "
                    f"{len(axes)} axes, {len(buttons)} buttons"
                )
                for i, v in enumerate(axes):
                    logger.info(f"  [PICO {source}] axis[{i}] = {v:.4f}")
                for i, v in enumerate(buttons):
                    logger.info(f"  [PICO {source}] button[{i}] = {int(v)}")

    # -------------------------------------------------------------------------
    # Periodic Log Loop
    # -------------------------------------------------------------------------

    def _start_log_loop(self) -> None:
        if self._log_thread is not None and self._log_thread.is_alive():
            return
        self._stop_event.clear()
        self._log_thread = threading.Thread(
            target=self._log_loop,
            daemon=True,
            name="PicoTeleopLogLoop",
        )
        self._log_thread.start()

    def _stop_log_loop(self) -> None:
        self._stop_event.set()
        if self._log_thread is not None:
            self._log_thread.join(timeout=1.0)
            self._log_thread = None

    def _log_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self.config.log_interval)
            if self._stop_event.is_set():
                break
            try:
                with self._lock:
                    self._log_raw_data()
            except Exception:
                logger.exception("Error in Pico log loop")

    def _log_raw_data(self) -> None:
        """Dump all current raw data."""
        # Log all known sources (not just left/right)
        all_sources = sorted(set(list(self._current_poses.keys()) + list(self._last_joy.keys())))

        if not all_sources:
            logger.info("[PICO] No data received yet")
            return

        for source in all_sources:
            pose = self._current_poses.get(source)
            joy = self._last_joy.get(source)

            parts = [f"[PICO {source}]"]

            if pose is not None:
                p = pose.position
                parts.append(f"pos=({p.x:.3f}, {p.y:.3f}, {p.z:.3f})")

            if joy is not None:
                axes = joy.axes or []
                buttons = joy.buttons or []
                axes_str = ", ".join(f"{v:.2f}" for v in axes)
                btn_str = "".join(str(int(b)) for b in buttons)
                parts.append(f"axes[{len(axes)}]=[{axes_str}]")
                parts.append(f"btn[{len(buttons)}]=[{btn_str}]")

            logger.info("  ".join(parts))

    # -------------------------------------------------------------------------
    # Deno Bridge Server
    # -------------------------------------------------------------------------

    def _start_server(self) -> None:
        """Launch the Deno WebSocket-to-LCM bridge server as a subprocess."""
        if self._server_process is not None and self._server_process.poll() is None:
            logger.warning("Deno bridge already running", pid=self._server_process.pid)
            return

        if shutil.which("deno") is None:
            logger.error(
                "Deno is not installed. Install it with: curl -fsSL https://deno.land/install.sh | sh"
            )
            return

        script = str(self._server_script)
        cmd = [
            "deno",
            "run",
            "--allow-net",
            "--allow-read",
            "--allow-run",
            "--allow-write",
            "--unstable-net",
            script,
        ]
        try:
            self._server_process = subprocess.Popen(cmd)
            logger.info(f"Deno bridge server started (pid {self._server_process.pid})")
        except OSError as e:
            logger.error(f"Failed to start Deno bridge: {e}")

    def _stop_server(self) -> None:
        """Terminate the Deno bridge server subprocess."""
        if self._server_process is None or self._server_process.poll() is not None:
            self._server_process = None
            return

        logger.info("Stopping Deno bridge server", pid=self._server_process.pid)
        self._server_process.send_signal(signal.SIGTERM)
        try:
            self._server_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Deno bridge did not exit, sending SIGKILL", pid=self._server_process.pid
            )
            self._server_process.kill()
            try:
                self._server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.error("Deno bridge did not exit after SIGKILL")
        logger.info("Deno bridge server stopped")
        self._server_process = None


pico_teleop_module = PicoTeleopModule.blueprint

__all__ = [
    "PicoTeleopConfig",
    "PicoTeleopModule",
    "pico_teleop_module",
]

if __name__ == "__main__":
    from dimos.core.blueprints import autoconnect
    from dimos.core.transport import LCMTransport

    blueprint = autoconnect(
        pico_teleop_module(),
    ).transports(
        {
            ("vr_left_pose", PoseStamped): LCMTransport("/vr_left_pose", PoseStamped),
            ("vr_right_pose", PoseStamped): LCMTransport("/vr_right_pose", PoseStamped),
            ("vr_left_joy", Joy): LCMTransport("/vr_left_joy", Joy),
            ("vr_right_joy", Joy): LCMTransport("/vr_right_joy", Joy),
        }
    )

    coordinator = blueprint.build()
    coordinator.loop()
