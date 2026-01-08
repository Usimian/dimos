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
PubSub Benchmark Tests - Compare throughput across transports.

Run with: pytest -m benchmark -v -s dimos/protocol/pubsub/test_spec_benchmark.py
"""

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
import time
from typing import Any

import pytest

from dimos.msgs.geometry_msgs import Vector3
from dimos.protocol.pubsub.lcmpubsub import LCM, Topic
from dimos.protocol.pubsub.memory import Memory
from dimos.protocol.pubsub.shmpubsub import PickleSharedMemory

# =============================================================================
# Benchmark Results Collection
# =============================================================================


@dataclass
class BenchmarkResult:
    transport: str
    test_type: str  # "message" or "image"
    duration: float
    sent: int
    received: int
    throughput_msg_s: float
    throughput_gb_s: float = 0.0
    img_size_kb: float = 0.0


@dataclass
class BenchmarkResults:
    results: list[BenchmarkResult] = field(default_factory=list)

    def add(self, result: BenchmarkResult) -> None:
        self.results.append(result)

    def print_summary(self) -> None:
        if not self.results:
            return

        print("\n")
        print("=" * 70)
        print("BENCHMARK SUMMARY")
        print("=" * 70)

        # Message throughput table
        msg_results = [r for r in self.results if r.test_type == "message"]
        if msg_results:
            print("\n## Message Throughput (small messages)\n")
            print(f"{'Transport':<12} {'msgs/sec':>15} {'Sent':>12} {'Received':>12}")
            print("-" * 55)
            for r in sorted(msg_results, key=lambda x: -x.throughput_msg_s):
                print(
                    f"{r.transport:<12} {r.throughput_msg_s:>15,.0f} {r.sent:>12,} {r.received:>12,}"
                )

        # Image bandwidth table
        img_results = [r for r in self.results if r.test_type == "image"]
        if img_results:
            print("\n## Image Bandwidth (900KB frames)\n")
            print(
                f"{'Transport':<12} {'GB/sec':>10} {'msgs/sec':>12} {'Sent':>10} {'Received':>10}"
            )
            print("-" * 58)
            for r in sorted(img_results, key=lambda x: -x.throughput_gb_s):
                print(
                    f"{r.transport:<12} {r.throughput_gb_s:>10.2f} {r.throughput_msg_s:>12,.0f} "
                    f"{r.sent:>10,} {r.received:>10,}"
                )

        print("\n" + "=" * 70)


@pytest.fixture(scope="module")
def benchmark_results():
    """Module-scoped fixture to collect benchmark results."""
    results = BenchmarkResults()
    yield results
    results.print_summary()


# =============================================================================
# Context Managers for each transport
# =============================================================================


@contextmanager
def memory_context():
    """Context manager for Memory PubSub implementation."""
    memory = Memory()
    yield memory


@contextmanager
def lcm_context():
    lcm_pubsub = LCM(autoconf=True)
    lcm_pubsub.start()
    yield lcm_pubsub
    lcm_pubsub.stop()


@contextmanager
def shm_context():
    shm_pubsub = PickleSharedMemory(prefer="cpu")
    shm_pubsub.start()
    yield shm_pubsub
    shm_pubsub.stop()


# ROS context - only available in devcontainer with ROS installed
ROS_AVAILABLE = False
ros_context = None

try:
    from dimos.protocol.pubsub.rospubsub import ROS, ROS_AVAILABLE, ROSTopic

    if ROS_AVAILABLE:

        @contextmanager
        def ros_context():
            ros_pubsub = ROS(node_name="benchmark_ros_pubsub")
            ros_pubsub.start()
            time.sleep(0.1)  # Give ROS time to initialize
            yield ros_pubsub
            ros_pubsub.stop()

except ImportError:
    pass


# =============================================================================
# Test Data
# =============================================================================

# Message throughput test data
message_testdata: list[tuple[Callable[[], Any], str, Any]] = [
    (memory_context, "memory", ["value1", "value2", "value3"]),
    (lcm_context, "lcm", [Vector3(1, 2, 3), Vector3(4, 5, 6), Vector3(7, 8, 9)]),
    (shm_context, "shm", [b"value1", b"value2", b"value3"]),
]

# Add ROS if available
if ROS_AVAILABLE and ros_context is not None:
    try:
        from std_msgs.msg import String as ROSString

        ros_values = [ROSString(data="v1"), ROSString(data="v2"), ROSString(data="v3")]
        message_testdata.append((ros_context, "ros", ros_values))
    except ImportError:
        pass

# Image bandwidth test data
bandwidth_testdata: list[tuple[Callable[[], Any], str]] = [
    (memory_context, "memory"),
    (lcm_context, "lcm"),
    (shm_context, "shm"),
]

if ROS_AVAILABLE and ros_context is not None:
    bandwidth_testdata.append((ros_context, "ros"))


# =============================================================================
# Fixtures
# =============================================================================


def _get_image_size_bytes(img) -> int:
    """Get size of image data in bytes."""
    if hasattr(img, "data"):
        return img.data.nbytes
    elif hasattr(img, "__sizeof__"):
        return img.__sizeof__()
    return 0


@pytest.fixture(scope="module")
def test_image():
    """Load test image once for all bandwidth tests.

    Resizes to ~1MB (640x480 BGR = 921,600 bytes) for realistic bandwidth testing.
    """
    from dimos.msgs.sensor_msgs.Image import Image
    from dimos.utils.data import get_data

    img_path = get_data("cafe.jpg")
    img = Image.from_file(img_path)
    return img.resize(640, 480)


# =============================================================================
# Benchmark Tests
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.parametrize("pubsub_context, transport_name, values", message_testdata)
def test_message_throughput(pubsub_context, transport_name, values, benchmark_results) -> None:
    """Measure message throughput with small messages for 5 seconds."""
    import threading

    # Determine topic based on transport
    if transport_name == "lcm":
        topic = Topic(topic="/benchmark_msg", lcm_type=Vector3)
    elif transport_name == "ros":
        from std_msgs.msg import String as ROSString

        topic = ROSTopic(topic="/benchmark_msg_ros", ros_type=ROSString)
    elif transport_name == "shm":
        topic = "/benchmark_msg_shm"
    else:
        topic = "benchmark_msg"

    with pubsub_context() as x:
        received_count = [0]
        msg_received = threading.Event()

        def callback(message, _topic) -> None:
            received_count[0] += 1
            msg_received.set()

        x.subscribe(topic, callback)

        # Publish messages synchronously for 5 seconds
        duration = 5.0
        start_time = time.time()
        sent_count = 0

        while time.time() - start_time < duration:
            msg_received.clear()
            x.publish(topic, values[0])
            sent_count += 1
            if not msg_received.wait(timeout=1.0):
                break

        elapsed = time.time() - start_time
        throughput = received_count[0] / elapsed if elapsed > 0 else 0

        # Record result
        benchmark_results.add(
            BenchmarkResult(
                transport=transport_name,
                test_type="message",
                duration=elapsed,
                sent=sent_count,
                received=received_count[0],
                throughput_msg_s=throughput,
            )
        )

        assert received_count[0] > 0, f"No messages received for {transport_name}"


@pytest.mark.benchmark
@pytest.mark.parametrize("pubsub_context, transport_name", bandwidth_testdata)
def test_image_bandwidth(pubsub_context, transport_name, test_image, benchmark_results) -> None:
    """Measure image throughput: send images for 5 seconds, calculate bandwidth."""
    import threading

    from dimos.msgs.sensor_msgs.Image import Image

    duration = 5.0
    img = test_image
    img_size = _get_image_size_bytes(img)

    # Set up topic and message based on transport
    if transport_name == "memory":
        topic = "bandwidth_test"
        msg = img
    elif transport_name == "lcm":
        topic = Topic(topic="/bandwidth_test", lcm_type=Image)
        msg = img
    elif transport_name == "shm":
        topic = "/bandwidth_test_shm"
        import pickle

        msg = pickle.dumps(img)
    elif transport_name == "ros":
        from sensor_msgs.msg import Image as ROSImage

        topic = ROSTopic(topic="/bandwidth_test_ros", ros_type=ROSImage)
        ros_msg = ROSImage()
        ros_msg.height = img.height
        ros_msg.width = img.width
        ros_msg.encoding = "bgr8"
        ros_msg.step = img.width * 3
        ros_msg.data = img.to_bgr().data.tobytes()
        msg = ros_msg
    else:
        pytest.skip(f"Unknown transport: {transport_name}")

    with pubsub_context() as x:
        received_count = [0]
        received_bytes = [0]
        msg_received = threading.Event()

        def callback(message, _topic) -> None:
            received_count[0] += 1
            received_bytes[0] += img_size
            msg_received.set()

        x.subscribe(topic, callback)

        # Send images for `duration` seconds, waiting for each to be received
        start_time = time.time()
        sent_count = 0

        while time.time() - start_time < duration:
            msg_received.clear()
            x.publish(topic, msg)
            sent_count += 1
            if not msg_received.wait(timeout=1.0):
                break

        elapsed = time.time() - start_time
        recv_bytes_total = received_bytes[0]
        recv_gbps = recv_bytes_total / (elapsed * 1_000_000_000) if elapsed > 0 else 0
        throughput_msg_s = received_count[0] / elapsed if elapsed > 0 else 0

        # Record result
        benchmark_results.add(
            BenchmarkResult(
                transport=transport_name,
                test_type="image",
                duration=elapsed,
                sent=sent_count,
                received=received_count[0],
                throughput_msg_s=throughput_msg_s,
                throughput_gb_s=recv_gbps,
                img_size_kb=img_size / 1024,
            )
        )

        assert received_count[0] > 0, f"No messages received for {transport_name}"
