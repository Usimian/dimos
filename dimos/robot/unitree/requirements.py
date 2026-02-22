# Copyright 2026 Dimensional Inc.
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

"""Blueprint requirement checks for Unitree robots."""

from __future__ import annotations

from dimos.core.global_config import global_config
from dimos.protocol.service.system_configurator import ClockSyncConfigurator, system_checks


def unitree_clock_sync() -> str | None:
    """Check clock synchronization for Unitree WebRTC connections.

    Skips the check for non-WebRTC connection types (sim, replay, mujoco).
    Runtime check of global_config is intentional — Go2/G1 blueprints are
    module-level constants that serve both hardware and sim modes.
    """
    if global_config.unitree_connection_type != "webrtc":
        return None
    return system_checks(ClockSyncConfigurator())()
