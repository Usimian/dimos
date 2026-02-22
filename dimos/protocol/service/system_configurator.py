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

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cache
import os
import platform
import re
import resource
import socket
import struct
import subprocess
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# ----------------------------- sudo helpers -----------------------------


@cache
def _is_root_user() -> bool:
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def sudo_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    if _is_root_user():
        return subprocess.run(list(args), **kwargs)
    return subprocess.run(["sudo", *args], **kwargs)


def _read_sysctl_int(name: str) -> int | None:
    try:
        result = subprocess.run(["sysctl", name], capture_output=True, text=True)
        if result.returncode != 0:
            print(
                f"[sysctl] ERROR: `sysctl {name}` rc={result.returncode} stderr={result.stderr!r}"
            )
            return None

        text = result.stdout.strip().replace(":", "=")
        if "=" not in text:
            print(f"[sysctl] ERROR: unexpected output for {name}: {text!r}")
            return None

        return int(text.split("=", 1)[1].strip())
    except Exception as error:
        print(f"[sysctl] ERROR: reading {name}: {error}")
        return None


def _write_sysctl_int(name: str, value: int) -> None:
    sudo_run("sysctl", "-w", f"{name}={value}", check=True, text=True, capture_output=False)


# -------------------------- base class for system config checks/requirements --------------------------


class SystemConfigurator(ABC):
    critical: bool = False

    @abstractmethod
    def check(self) -> bool:
        """Return True if configured. Log errors and return False on uncertainty."""
        raise NotImplementedError

    @abstractmethod
    def explanation(self) -> str | None:
        """
        Return a human-readable summary of what would be done (sudo commands) if not configured.
        Return None when no changes are needed.
        """
        raise NotImplementedError

    @abstractmethod
    def fix(self) -> None:
        """Apply fixes (may attempt sudo, catch, and apply fallback measures if needed)."""
        raise NotImplementedError


# ----------------------------- generic enforcement of system configs -----------------------------


def configure_system(checks: list[SystemConfigurator], check_only: bool = False) -> None:
    if os.environ.get("CI"):
        print("CI environment detected: skipping system configuration.")
        return

    # run checks
    failing = [check for check in checks if not check.check()]
    if not failing:
        return

    # ask for permission to modify system
    explanations: list[str] = [msg for check in failing if (msg := check.explanation()) is not None]

    if explanations:
        print("System configuration changes are recommended/required:\n")
        print("\n\n".join(explanations))
        print()

    if check_only:
        return

    try:
        answer = input("Apply these changes now? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""

    if answer not in ("y", "yes"):
        if any(check.critical for check in failing):
            raise SystemExit(1)
        return

    for check in failing:
        try:
            check.fix()
        except subprocess.CalledProcessError as error:
            if check.critical:
                print(f"Critical fix failed rc={error.returncode}")
                print(f"stdout: {error.stdout}")
                print(f"stderr: {error.stderr}")
                raise
            print(f"Optional improvement failed: rc={error.returncode}")
            print(f"stdout: {error.stdout}")
            print(f"stderr: {error.stderr}")

    print("System configuration completed.")


# ----------------------------- bridge: SystemConfigurator → Blueprint.requirements() -----------------------------


def system_checks(*configurators: SystemConfigurator) -> Callable[[], str | None]:
    """Wrap SystemConfigurator instances into a Blueprint.requirements()-compatible callable.

    Returns a function that runs configure_system() and converts SystemExit
    (raised when a critical check is declined) into an error string.
    Non-critical declines return None (proceed with degraded state).
    """

    def _check() -> str | None:
        try:
            configure_system(list(configurators))
        except SystemExit:
            labels = [type(c).__name__ for c in configurators]
            return f"Required system configuration was declined: {', '.join(labels)}"
        return None

    return _check


# ------------------------------ specific checks: clock sync ------------------------------


class ClockSyncConfigurator(SystemConfigurator):
    """Check that the local clock is within MAX_OFFSET_SECONDS of NTP time.

    Uses a pure-Python NTP query (RFC 4330 SNTPv4) so there are no external
    dependencies.  If the NTP server is unreachable the check *passes* — we
    don't want unrelated network issues to block robot startup.
    """

    critical = False
    MAX_OFFSET_SECONDS = 0.1  # 100 ms per issue spec
    NTP_SERVER = "pool.ntp.org"
    NTP_PORT = 123
    NTP_TIMEOUT = 2  # seconds

    def __init__(self) -> None:
        self._offset: float | None = None  # seconds, filled by check()

    # ---- NTP query ----

    @staticmethod
    def _ntp_offset(server: str = "pool.ntp.org", port: int = 123, timeout: float = 2) -> float:
        """Return clock offset in seconds (local - NTP).  Raises on failure."""
        # Minimal SNTPv4 request: LI=0, VN=4, Mode=3 → first byte = 0x23
        msg = b"\x23" + b"\x00" * 47
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            t1 = time.time()
            sock.sendto(msg, (server, port))
            data, _ = sock.recvfrom(1024)
            t4 = time.time()
        finally:
            sock.close()

        if len(data) < 48:
            raise ValueError(f"NTP response too short ({len(data)} bytes)")

        # Transmit Timestamp starts at byte 40 (seconds at 40, fraction at 44)
        ntp_secs: int = struct.unpack("!I", data[40:44])[0]
        ntp_frac: int = struct.unpack("!I", data[44:48])[0]
        # NTP epoch is 1900-01-01; Unix epoch is 1970-01-01
        ntp_time: float = ntp_secs - 2208988800 + ntp_frac / (2**32)

        # Simplified offset: assume symmetric delay
        t_server = ntp_time
        rtt = t4 - t1
        offset: float = t_server - (t1 + rtt / 2)
        return offset

    # ---- SystemConfigurator interface ----

    def check(self) -> bool:
        try:
            self._offset = self._ntp_offset(self.NTP_SERVER, self.NTP_PORT, self.NTP_TIMEOUT)
        except (TimeoutError, OSError, ValueError) as exc:
            print(f"[clock-sync] NTP query failed ({exc}); assuming clock is OK")
            self._offset = None
            return True  # graceful degradation — don't block on network issues

        if abs(self._offset) <= self.MAX_OFFSET_SECONDS:
            return True

        print(
            f"[clock-sync] WARNING: clock offset is {self._offset * 1000:+.1f} ms "
            f"(threshold: ±{self.MAX_OFFSET_SECONDS * 1000:.0f} ms)"
        )
        return False

    def explanation(self) -> str | None:
        if self._offset is None:
            return None
        offset_ms = self._offset * 1000
        system = platform.system()
        if system == "Linux":
            cmd = "sudo timedatectl set-ntp true && sudo systemctl restart systemd-timesyncd"
        elif system == "Darwin":
            cmd = "sudo sntp -sS pool.ntp.org"
        else:
            cmd = "(manual NTP sync required for your platform)"
        return (
            f"- Clock sync: local clock is off by {offset_ms:+.1f} ms "
            f"(threshold: ±{self.MAX_OFFSET_SECONDS * 1000:.0f} ms)\n"
            f"  Fix: {cmd}"
        )

    def fix(self) -> None:
        system = platform.system()
        if system == "Linux":
            sudo_run(
                "timedatectl",
                "set-ntp",
                "true",
                check=True,
                text=True,
                capture_output=True,
            )
            sudo_run(
                "systemctl",
                "restart",
                "systemd-timesyncd",
                check=True,
                text=True,
                capture_output=True,
            )
        elif system == "Darwin":
            sudo_run(
                "sntp",
                "-sS",
                self.NTP_SERVER,
                check=True,
                text=True,
                capture_output=True,
            )
        else:
            print(f"[clock-sync] No automatic fix available for {system}")


# ------------------------------ specific checks: multicast ------------------------------


class MulticastConfiguratorLinux(SystemConfigurator):
    critical = True
    MULTICAST_PREFIX = "224.0.0.0/4"

    def __init__(self, loopback_interface: str = "lo"):
        self.loopback_interface = loopback_interface

        self.loopback_ok: bool | None = None
        self.route_ok: bool | None = None

        self.enable_multicast_cmd = [
            "ip",
            "link",
            "set",
            self.loopback_interface,
            "multicast",
            "on",
        ]
        self.add_route_cmd = [
            "ip",
            "route",
            "add",
            self.MULTICAST_PREFIX,
            "dev",
            self.loopback_interface,
        ]

    def check(self) -> bool:
        # Verify `ip` exists (iproute2)
        try:
            subprocess.run(["ip", "-V"], capture_output=True, text=True, check=False)
        except FileNotFoundError as error:
            print(
                f"ERROR: `ip` not found (iproute2 missing, did you install system requirements?): {error}"
            )
            self.loopback_ok = self.route_ok = False
            return False
        except Exception as error:
            print(f"ERROR: failed probing `ip`: {error}")
            self.loopback_ok = self.route_ok = False
            return False

        # check MULTICAST on loopback
        try:
            result = subprocess.run(
                ["ip", "-o", "link", "show", self.loopback_interface],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(
                    f"ERROR: `ip link show {self.loopback_interface}` rc={result.returncode} "
                    f"stderr={result.stderr!r}"
                )
                self.loopback_ok = False
            else:
                match = re.search(r"<([^>]*)>", result.stdout)
                flags = {
                    flag.strip().upper()
                    for flag in (match.group(1).split(",") if match else [])
                    if flag.strip()
                }
                self.loopback_ok = "MULTICAST" in flags
        except Exception as error:
            print(f"ERROR: failed checking loopback multicast: {error}")
            self.loopback_ok = False

        # Check if multicast route exists
        try:
            result = subprocess.run(
                ["ip", "-o", "route", "show", self.MULTICAST_PREFIX],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(
                    f"ERROR: `ip route show {self.MULTICAST_PREFIX}` rc={result.returncode} "
                    f"stderr={result.stderr!r}"
                )
                self.route_ok = False
            else:
                self.route_ok = bool(result.stdout.strip())
        except Exception as error:
            print(f"ERROR: failed checking multicast route: {error}")
            self.route_ok = False

        return bool(self.loopback_ok and self.route_ok)

    def explanation(self) -> str | None:
        output = ""
        if not self.loopback_ok:
            output += f"- Multicast: sudo {' '.join(self.enable_multicast_cmd)}\n"
        if not self.route_ok:
            output += f"- Multicast: sudo {' '.join(self.add_route_cmd)}\n"
        return output

    def fix(self) -> None:
        if not self.loopback_ok:
            sudo_run(*self.enable_multicast_cmd, check=True, text=True, capture_output=True)
        if not self.route_ok:
            sudo_run(*self.add_route_cmd, check=True, text=True, capture_output=True)


class MulticastConfiguratorMacOS(SystemConfigurator):
    critical = True

    def __init__(self, loopback_interface: str = "lo0"):
        self.loopback_interface = loopback_interface
        self.add_route_cmd = [
            "route",
            "add",
            "-net",
            "224.0.0.0/4",
            "-interface",
            self.loopback_interface,
        ]

    def check(self) -> bool:
        # `netstat -nr` shows the routing table. We search for a 224/4 route entry.
        try:
            result = subprocess.run(["netstat", "-nr"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"ERROR: `netstat -nr` rc={result.returncode} stderr={result.stderr!r}")
                return False

            route_ok = ("224.0.0.0/4" in result.stdout) or ("224.0.0/4" in result.stdout)
            return bool(route_ok)
        except Exception as error:
            print(f"ERROR: failed checking multicast route via netstat: {error}")
            return False

    def explanation(self) -> str | None:
        return f"Multicast: - sudo {' '.join(self.add_route_cmd)}"

    def fix(self) -> None:
        sudo_run(*self.add_route_cmd, check=True, text=True, capture_output=True)


# ------------------------------ specific checks: buffers ------------------------------

IDEAL_RMEM_SIZE = 67_108_864  # 64MB


class BufferConfiguratorLinux(SystemConfigurator):
    critical = False

    TARGET_RMEM_SIZE = IDEAL_RMEM_SIZE

    def __init__(self) -> None:
        self.needs: list[tuple[str, int]] = []  # (key, target_value)

    def check(self) -> bool:
        self.needs.clear()
        for key, target in [
            ("net.core.rmem_max", self.TARGET_RMEM_SIZE),
            ("net.core.rmem_default", self.TARGET_RMEM_SIZE),
        ]:
            current = _read_sysctl_int(key)
            if current is None or current < target:
                self.needs.append((key, target))
        return not self.needs

    def explanation(self) -> str | None:
        lines = []
        for key, target in self.needs:
            lines.append(f"- socket buffer optimization: sudo sysctl -w {key}={target}")
        return "\n".join(lines)

    def fix(self) -> None:
        for key, target in self.needs:
            _write_sysctl_int(key, target)


class BufferConfiguratorMacOS(SystemConfigurator):
    critical = False
    MAX_POSSIBLE_RECVSPACE = 2_097_152
    MAX_POSSIBLE_BUFFER_SIZE = 8_388_608
    MAX_POSSIBLE_DGRAM_SIZE = 65_535
    # these values are based on macos 26

    TARGET_BUFFER_SIZE = MAX_POSSIBLE_BUFFER_SIZE
    TARGET_RECVSPACE = MAX_POSSIBLE_RECVSPACE  # we want this to be IDEAL_RMEM_SIZE but MacOS 26 (and probably in general) doesn't support it
    TARGET_DGRAM_SIZE = MAX_POSSIBLE_DGRAM_SIZE

    def __init__(self) -> None:
        self.needs: list[tuple[str, int]] = []

    def check(self) -> bool:
        self.needs.clear()
        for key, target in [
            ("kern.ipc.maxsockbuf", self.TARGET_BUFFER_SIZE),
            ("net.inet.udp.recvspace", self.TARGET_RECVSPACE),
            ("net.inet.udp.maxdgram", self.TARGET_DGRAM_SIZE),
        ]:
            current = _read_sysctl_int(key)
            if current is None or current < target:
                self.needs.append((key, target))
        return not self.needs

    def explanation(self) -> str | None:
        lines = []
        for key, target in self.needs:
            lines.append(f"- sudo sysctl -w {key}={target}")
        return "\n".join(lines)

    def fix(self) -> None:
        for key, target in self.needs:
            _write_sysctl_int(key, target)


# ------------------------------ specific checks: ulimit ------------------------------


class MaxFileConfiguratorMacOS(SystemConfigurator):
    """Ensure the open file descriptor limit (ulimit -n) is at least TARGET_FILE_COUNT_LIMIT."""

    critical = False
    TARGET_FILE_COUNT_LIMIT = 65536

    def __init__(self, target: int = TARGET_FILE_COUNT_LIMIT):
        self.target = target
        self.current_soft: int = 0
        self.current_hard: int = 0
        self.can_fix_without_sudo: bool = False

    def check(self) -> bool:
        try:
            self.current_soft, self.current_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        except Exception as error:
            print(f"[ulimit] ERROR: failed to get RLIMIT_NOFILE: {error}")
            return False

        if self.current_soft >= self.target:
            return True

        # Check if we can raise to target without sudo (hard limit is high enough)
        self.can_fix_without_sudo = self.current_hard >= self.target
        return False

    def explanation(self) -> str | None:
        lines = []
        if self.can_fix_without_sudo:
            lines.append(f"- Raise soft file count limit to {self.target} (no sudo required)")
        else:
            lines.append(f"- Raise soft file count limit to {min(self.target, self.current_hard)}")
            lines.append(
                f"- Raise hard limit via: sudo launchctl limit maxfiles {self.target} {self.target}"
            )
        return "\n".join(lines)

    def fix(self) -> None:
        if self.current_soft >= self.target:
            return

        if self.can_fix_without_sudo:
            # Hard limit is sufficient, just raise the soft limit
            try:
                resource.setrlimit(resource.RLIMIT_NOFILE, (self.target, self.current_hard))
            except Exception as error:
                print(f"[ulimit] ERROR: failed to set soft limit: {error}")
                raise
        else:
            # Need to raise both soft and hard limits via launchctl
            try:
                sudo_run(
                    "launchctl",
                    "limit",
                    "maxfiles",
                    str(self.target),
                    str(self.target),
                    check=True,
                    text=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as error:
                print(f"[ulimit] WARNING: launchctl failed: {error.stderr}")
                # Fallback: raise soft limit as high as the current hard limit allows
                if self.current_hard > self.current_soft:
                    try:
                        resource.setrlimit(
                            resource.RLIMIT_NOFILE, (self.current_hard, self.current_hard)
                        )
                    except Exception as fallback_error:
                        print(f"[ulimit] ERROR: fallback also failed: {fallback_error}")
                raise

            # After launchctl, try to apply the new limit to the current process
            try:
                resource.setrlimit(resource.RLIMIT_NOFILE, (self.target, self.target))
            except Exception as error:
                print(
                    f"[ulimit] WARNING: could not apply to current process (restart may be required): {error}"
                )
