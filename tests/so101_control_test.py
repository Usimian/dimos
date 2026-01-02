import time

from dimos.hardware.so101_arm import SO101Arm
from dimos.msgs.geometry_msgs import Pose, Quaternion, Vector3
from dimos.utils.transform_utils import euler_to_quaternion


def test_gripper_open_close(port: str = "/dev/ttyACM0", wait_time: float = 2.0) -> None:
    """
    Test function that opens the gripper to max and then closes it.
    
    Args:
        port: Serial port for the SO101 arm (default: "/dev/ttyACM0")
        wait_time: Time to wait between open and close operations (default: 2.0 seconds)
    """
    print("Initializing SO101Arm...")
    arm = SO101Arm(port=port)
    print("SO101Arm initialized")
    
    try:
        print("Opening gripper to max...")
        arm.release_gripper()
        time.sleep(wait_time)
        print("gripper feedback: ", arm.get_gripper_feedback())
        
        print("Closing gripper...")
        arm.close_gripper()
        time.sleep(wait_time)
        print("gripper feedback: ", arm.get_gripper_feedback())
        print("Gripper test completed successfully!")
        time.sleep(1.0)
        
        # Move end-effector 10 cm in z-axis
        print("Getting current end-effector pose...")
        current_pose = arm.get_ee_pose()
        print(f"Current position: x={current_pose.position.x:.3f}, y={current_pose.position.y:.3f}, z={current_pose.position.z:.3f}")
        
        # Create new pose with z offset of 10 cm (0.1 m)
        new_position = Vector3(
            current_pose.position.x,
            current_pose.position.y + 0.1,
            current_pose.position.z
        )
        new_pose = Pose(
            position=new_position,
            orientation=current_pose.orientation
        )
        
        print(f"Moving end-effector to {new_position} (10 cm higher)...")
        arm.cmd_ee_pose(new_pose)
        time.sleep(wait_time)
        current_pose = arm.get_ee_pose()
        print(f"Current position: x={current_pose.position.x:.3f}, y={current_pose.position.y:.3f}, z={current_pose.position.z:.3f}")
        print("End-effector movement completed!")
    finally:
        arm.disable()

if __name__ == "__main__":
    test_gripper_open_close()