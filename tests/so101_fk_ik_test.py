#!/usr/bin/env python3

"""
Test script for SO101Arm - Gripper open/close and end-effector movement test.

Run with: python tests/so101_fk_ik_test.py

This script tests:

1. Opening gripper to max
2. Closing gripper
3. Moving end-effector with position offset and rotation

Uses LerobotKinematics (lerobot SDK) for FK/IK calculations.
"""

import time

import numpy as np
from scipy.spatial.transform import Rotation as R

from dimos.hardware.so101_arm import SO101Arm
from dimos.msgs.geometry_msgs import Pose, Quaternion, Vector3


def test_gripper_and_movement(port: str = "/dev/ttyACM0", wait_time: float = 2.0) -> None:
    """
    Test function that opens the gripper to max, closes it, then moves the
    end-effector with position offset and rotation.

    Args:
        port: Serial port for the SO101 arm (default: "/dev/ttyACM0")
        wait_time: Time to wait between operations (default: 2.0 seconds)
    """
    print("=" * 60)
    print("SO101Arm Gripper and Movement Test")
    print("=" * 60)
    
    print("\nInitializing SO101Arm...")
    arm = SO101Arm(port=port)
    print("SO101Arm initialized")
    
    original_pose = None
    
    try:
        # Test 1: Open gripper
        print("\n" + "=" * 60)
        print("TEST 1: Opening gripper to max...")
        print("=" * 60)
        arm.release_gripper()
        time.sleep(wait_time)
        position_m, effort = arm.get_gripper_feedback()
        print(f"✓ Gripper opened - Position: {position_m:.3f} m, Effort: {effort:.3f}")
        
        # Test 2: Close gripper
        print("\n" + "=" * 60)
        print("TEST 2: Closing gripper...")
        print("=" * 60)
        arm.close_gripper()
        time.sleep(wait_time)
        position_m, effort = arm.get_gripper_feedback()
        print(f"✓ Gripper closed - Position: {position_m:.3f} m, Effort: {effort:.3f}")
        
        # Test 3: Get current pose and move end-effector
        print("\n" + "=" * 60)
        print("TEST 3: Getting current end-effector pose...")
        print("=" * 60)
        current_pose = arm.get_ee_pose()
        # Store original pose to restore later
        original_pose = Pose(
            position=Vector3(
                current_pose.position.x,
                current_pose.position.y,
                current_pose.position.z,
            ),
            orientation=Quaternion(
                current_pose.orientation.x,
                current_pose.orientation.y,
                current_pose.orientation.z,
                current_pose.orientation.w,
            ),
        )
        print(
            f"  Current position: x={current_pose.position.x:.3f}, "
            f"y={current_pose.position.y:.3f}, z={current_pose.position.z:.3f}"
        )
        print(
            f"  Current orientation: x={current_pose.orientation.x:.3f}, "
            f"y={current_pose.orientation.y:.3f}, z={current_pose.orientation.z:.3f}, "
            f"w={current_pose.orientation.w:.3f}"
        )
        
        # Create new pose with position offset
        # Offset: +5cm in x, +10cm in y, -10cm in z
        new_position = Vector3(
            current_pose.position.x - 0.05,
            current_pose.position.y + 0.2,
            current_pose.position.z - 0.05,
        )
        
        # Rotate current orientation by 90 degrees around y-axis
        current_quat_xyzw = [
            current_pose.orientation.x,
            current_pose.orientation.y,
            current_pose.orientation.z,
            current_pose.orientation.w,
        ]
        current_rot = R.from_quat(current_quat_xyzw)
        y_rotation = R.from_euler("y", 90.0, degrees=True)
        new_rot = current_rot * y_rotation
        new_quat_xyzw = new_rot.as_quat()
        
        # Quaternion accepts positional args (x, y, z, w) or a sequence
        new_orientation = Quaternion(
            new_quat_xyzw[0],
            new_quat_xyzw[1],
            new_quat_xyzw[2],
            new_quat_xyzw[3],
        )
        
        new_pose = Pose(position=new_position, orientation=new_orientation)
        
        print("\n" + "=" * 60)
        print("TEST 4: Moving end-effector...")
        print("=" * 60)
        print(
            f"  Target position: x={new_position.x:.3f}, "
            f"y={new_position.y:.3f}, z={new_position.z:.3f}"
        )
        print(
            f"  Target orientation: x={new_orientation.x:.3f}, "
            f"y={new_orientation.y:.3f}, z={new_orientation.z:.3f}, "
            f"w={new_orientation.w:.3f}"
        )
        print("  Using PTP mode (duration: 2.0 seconds)...")
        
        arm.cmd_ee_pose(new_pose, line_mode=False, duration=2.0)
        time.sleep(2.5)  # Wait for movement to complete
        
        # Test 5: Verify final position
        print("\n" + "=" * 60)
        print("TEST 5: Verifying final end-effector position...")
        print("=" * 60)
        final_pose = arm.get_ee_pose()
        print(
            f"  Final position: x={final_pose.position.x:.3f}, "
            f"y={final_pose.position.y:.3f}, z={final_pose.position.z:.3f}"
        )
        print(
            f"  Final orientation: x={final_pose.orientation.x:.3f}, "
            f"y={final_pose.orientation.y:.3f}, z={final_pose.orientation.z:.3f}, "
            f"w={final_pose.orientation.w:.3f}"
        )
        
        # Calculate position error
        pos_error = np.array(
            [
                final_pose.position.x - new_position.x,
                final_pose.position.y - new_position.y,
                final_pose.position.z - new_position.z,
            ]
        )
        pos_error_norm = np.linalg.norm(pos_error)
        print(f"\n  Position error: {pos_error_norm*1000:.2f} mm")
        print(f"  Position error components: x={pos_error[0]*1000:.2f} mm, "
              f"y={pos_error[1]*1000:.2f} mm, z={pos_error[2]*1000:.2f} mm")
        
        # Calculate orientation error (quaternion distance)
        final_quat_xyzw = [
            final_pose.orientation.x,
            final_pose.orientation.y,
            final_pose.orientation.z,
            final_pose.orientation.w,
        ]
        final_rot = R.from_quat(final_quat_xyzw)
        rot_error = (new_rot.inv() * final_rot).as_rotvec()
        rot_error_deg = np.linalg.norm(rot_error) * 180 / np.pi
        print(f"  Orientation error: {rot_error_deg:.2f} degrees")
        
        print("\n" + "=" * 60)
        print("All tests completed successfully!")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\n✗ Test interrupted by user")
    except Exception as e:
        print(f"\n\n✗ Error during test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Restore original pose before disabling
        if original_pose is not None:
            try:
                print("\n" + "=" * 60)
                print("Restoring original end-effector pose...")
                print("=" * 60)
                print(
                    f"  Restoring position: x={original_pose.position.x:.3f}, "
                    f"y={original_pose.position.y:.3f}, z={original_pose.position.z:.3f}"
                )
                print(
                    f"  Restoring orientation: x={original_pose.orientation.x:.3f}, "
                    f"y={original_pose.orientation.y:.3f}, z={original_pose.orientation.z:.3f}, "
                    f"w={original_pose.orientation.w:.3f}"
                )
                arm.cmd_ee_pose(original_pose, line_mode=False, duration=2.0)
                time.sleep(2.5)  # Wait for movement to complete
                print("✓ Original pose restored")
            except Exception as restore_error:
                print(f"⚠ Warning: Failed to restore original pose: {restore_error}")
        
        print("\nDisabling arm...")
        arm.disable()
        print("✓ Arm disabled")


if __name__ == "__main__":
    test_gripper_and_movement()

