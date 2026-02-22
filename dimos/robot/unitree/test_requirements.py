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

from unittest.mock import MagicMock, patch

from dimos.robot.unitree.requirements import unitree_clock_sync


class TestUnitreeClockSync:
    def test_skips_for_replay_connection(self) -> None:
        with patch("dimos.robot.unitree.requirements.global_config") as mock_config:
            mock_config.unitree_connection_type = "replay"
            assert unitree_clock_sync() is None

    def test_skips_for_mujoco_connection(self) -> None:
        with patch("dimos.robot.unitree.requirements.global_config") as mock_config:
            mock_config.unitree_connection_type = "mujoco"
            assert unitree_clock_sync() is None

    def test_skips_for_sim_connection(self) -> None:
        with patch("dimos.robot.unitree.requirements.global_config") as mock_config:
            mock_config.unitree_connection_type = "sim"
            assert unitree_clock_sync() is None

    def test_runs_clock_sync_for_webrtc(self) -> None:
        with patch("dimos.robot.unitree.requirements.global_config") as mock_config:
            mock_config.unitree_connection_type = "webrtc"
            with patch("dimos.robot.unitree.requirements.system_checks") as mock_system_checks:
                mock_check_fn = MagicMock(return_value=None)
                mock_system_checks.return_value = mock_check_fn
                result = unitree_clock_sync()
                assert result is None
                mock_system_checks.assert_called_once()
                mock_check_fn.assert_called_once()

    def test_returns_error_from_system_checks(self) -> None:
        with patch("dimos.robot.unitree.requirements.global_config") as mock_config:
            mock_config.unitree_connection_type = "webrtc"
            with patch("dimos.robot.unitree.requirements.system_checks") as mock_system_checks:
                mock_check_fn = MagicMock(
                    return_value="Required system configuration was declined: ClockSyncConfigurator"
                )
                mock_system_checks.return_value = mock_check_fn
                result = unitree_clock_sync()
                assert result is not None
                assert "ClockSyncConfigurator" in result
