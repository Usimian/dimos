"""Kinematics helpers for the SO-ARM101 manipulator.

Provides:
- IK solver (Pinocchio-based, adapted from ../so101_ik_standalone)
- Forward kinematics utility
- Manipulability metric

RPC methods expose IK/FK for use by higher-level controllers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from dimos.core import rpc

logger = logging.getLogger(__name__)

# Optional heavy deps are imported lazily
try:  # pragma: no cover - import guard
    import numpy as np
    import pinocchio as pin
    from scipy.spatial.transform import Rotation as R
except Exception:  # noqa: BLE001
    np = None
    pin = None
    R = None


class SOArm101IKSolver:
    """Pinocchio-based IK solver for SO-ARM101 (5 active joints)."""

    def __init__(self, urdf_path: str):
        if np is None or pin is None or R is None:
            raise ImportError("pinocchio, scipy, and numpy are required for IK")

        self.model = pin.buildModelFromUrdf(urdf_path)
        self.data = self.model.createData()

        self.joint_names = [
            "shoulder_pan",
            "shoulder_lift",
            "elbow_flex",
            "wrist_flex",
            "wrist_roll",
        ]
        self.joint_ids = {}
        for name in self.joint_names:
            try:
                self.joint_ids[name] = self.model.getJointId(name)
            except Exception:  # noqa: BLE001
                logger.error("Joint %s not found in URDF", name)

        self.ee_frame_name = "wrist_link"
        try:
            self.ee_frame_id = self.model.getFrameId(self.ee_frame_name)
        except Exception:  # noqa: BLE001
            self.ee_frame_name = "wrist"
            self.ee_frame_id = self.model.getFrameId(self.ee_frame_name)

        # Tunables (kept from standalone solver)
        self.max_iterations = 30
        self.position_tolerance = 0.005
        self.orientation_tolerance = 0.02
        self.lambda_min = 1e-6
        self.lambda_max = 0.1
        self.manipulability_threshold = 0.01
        self.max_position_step = 0.05
        self.max_rotation_step = 0.1

        self.joint_limits_lower = self.model.lowerPositionLimit[:5]
        self.joint_limits_upper = self.model.upperPositionLimit[:5]

    # ===== Standalone solver methods (trimmed/adapted) =====

    def _clamp_step(self, vec, max_norm):
        norm = np.linalg.norm(vec)
        if norm > max_norm and norm > 0.0:
            vec = vec * (max_norm / norm)
        return vec

    def _init_q(self, current_joints):
        if current_joints is not None:
            q = np.zeros(self.model.nq)
            q[:5] = current_joints[:5]
        else:
            q = (self.joint_limits_lower + self.joint_limits_upper) / 2.0
            q = np.pad(q, (0, self.model.nq - 5), "constant")
        return q

    def solve_ik(self, target_position, target_orientation=None, current_joints=None, position_only=False):
        if np is None or pin is None:
            raise RuntimeError("IK dependencies not installed")

        q = self._init_q(current_joints)
        target_rot = None
        if target_orientation is not None and not position_only:
            target_orientation = np.asarray(target_orientation)
            if target_orientation.shape == (4,):
                target_rot = R.from_quat(target_orientation).as_matrix()
            else:
                target_rot = target_orientation

        best_q = q[:5].copy()
        best_error = float("inf")
        max_iter = 20 if position_only else self.max_iterations

        for _ in range(max_iter):
            pin.framesForwardKinematics(self.model, self.data, q)
            current_pose = self.data.oMf[self.ee_frame_id]
            current_pos = current_pose.translation
            current_rot = current_pose.rotation

            pos_err = target_position - current_pos
            if target_rot is not None and not position_only:
                rot_err_mat = target_rot @ current_rot.T
                rot_err = pin.log3(rot_err_mat)
            else:
                rot_err = np.zeros(3)

            pos_norm = np.linalg.norm(pos_err)
            rot_norm = np.linalg.norm(rot_err)

            if pos_norm < best_error:
                best_error = pos_norm
                best_q = q[:5].copy()

            if pos_norm < self.position_tolerance and rot_norm < self.orientation_tolerance:
                return True, q[:5]

            pos_err = self._clamp_step(pos_err, self.max_position_step)
            rot_err = self._clamp_step(rot_err, self.max_rotation_step)
            error = np.hstack([pos_err, rot_err])

            J = pin.computeFrameJacobian(
                self.model, self.data, q, self.ee_frame_id, pin.ReferenceFrame.LOCAL_WORLD_ALIGNED
            )
            J_arm = J[:3, :3] if position_only else J[:, :5]

            manipulability = np.sqrt(np.linalg.det(J_arm @ J_arm.T))
            lambda_dls = self.lambda_max if manipulability < self.manipulability_threshold else self.lambda_min

            JtJ = J_arm.T @ J_arm
            n_joints = J_arm.shape[1]
            damped_JtJ = JtJ + lambda_dls * np.eye(n_joints)

            try:
                rhs = error[:3] if position_only else error
                dq = np.linalg.solve(damped_JtJ, J_arm.T @ rhs)
            except np.linalg.LinAlgError:
                dq = np.linalg.pinv(J_arm) @ (error[:3] if position_only else error)

            dq = self._clamp_step(dq, 0.2)

            if position_only:
                q[:3] += dq
                q[:3] = np.clip(q[:3], self.joint_limits_lower[:3], self.joint_limits_upper[:3])
            else:
                q[:5] += dq
                q[:5] = np.clip(q[:5], self.joint_limits_lower, self.joint_limits_upper)

        return False, best_q

    def solve_position_ik(self, target_position, current_joints=None):
        if np is None or pin is None:
            raise RuntimeError("IK dependencies not installed")

        q = self._init_q(current_joints)
        original_wrist = q[3:5].copy()
        best_q = q[:5].copy()
        best_error = float("inf")

        for _ in range(15):
            pin.framesForwardKinematics(self.model, self.data, q)
            current_pose = self.data.oMf[self.ee_frame_id]
            current_pos = current_pose.translation

            pos_err = target_position - current_pos
            pos_norm = np.linalg.norm(pos_err)

            if pos_norm < best_error:
                best_error = pos_norm
                best_q = q[:5].copy()

            if pos_norm < self.position_tolerance:
                q[3:5] = original_wrist
                return True, q[:5]

            pos_err = self._clamp_step(pos_err, self.max_position_step)

            J_full = pin.computeFrameJacobian(
                self.model, self.data, q, self.ee_frame_id, pin.ReferenceFrame.LOCAL_WORLD_ALIGNED
            )
            J_pos = J_full[:3, :3]
            lambda_dls = 0.01
            JtJ = J_pos.T @ J_pos + lambda_dls * np.eye(3)
            try:
                dq = np.linalg.solve(JtJ, J_pos.T @ pos_err)
            except Exception:  # noqa: BLE001
                dq = np.linalg.pinv(J_pos) @ pos_err

            dq = self._clamp_step(dq, 0.3)
            q[:3] += dq * 0.1
            q[:3] = np.clip(q[:3], self.joint_limits_lower[:3], self.joint_limits_upper[:3])

        best_q[3:5] = original_wrist
        return False, best_q

    def get_end_effector_pose(self, joint_positions):
        if np is None or pin is None or R is None:
            raise RuntimeError("IK dependencies not installed")

        q = self._init_q(joint_positions)
        pin.framesForwardKinematics(self.model, self.data, q)
        pose = self.data.oMf[self.ee_frame_id]
        position = pose.translation
        quaternion = R.from_matrix(pose.rotation).as_quat()
        return position, quaternion

    def compute_manipulability(self, joint_positions):
        if np is None or pin is None:
            raise RuntimeError("IK dependencies not installed")

        q = self._init_q(joint_positions)
        pin.framesForwardKinematics(self.model, self.data, q)
        J = pin.computeFrameJacobian(
            self.model, self.data, q, self.ee_frame_id, pin.ReferenceFrame.LOCAL_WORLD_ALIGNED
        )
        J_arm = J[:, :5]
        return float(np.sqrt(np.linalg.det(J_arm @ J_arm.T)))


class KinematicsComponent:
    """IK/FK RPC component for SO-ARM101."""

    def __init__(self, urdf_path: str | None = None):
        self.urdf_path = Path(urdf_path) if urdf_path else Path(__file__).resolve().parent.parent / "so101.urdf"
        self.solver: SOArm101IKSolver | None = None

    def initialize(self):
        if np is None or pin is None or R is None:
            logger.warning("IK disabled: install numpy, pinocchio, scipy to enable kinematics RPCs")
            return

        if not self.urdf_path.exists():
            logger.error("IK disabled: URDF not found at %s", self.urdf_path)
            return

        try:
            self.solver = SOArm101IKSolver(str(self.urdf_path))
            logger.info("SO-ARM101 IK solver loaded from %s", self.urdf_path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to initialize IK solver: %s", exc)
            self.solver = None

    # ============= RPC Methods =============

    def _ensure_solver(self):
        if self.solver is None:
            return {"success": False, "error": "IK solver unavailable (missing deps or URDF)"}
        return None

    @rpc
    def solve_ik(
        self,
        position: Iterable[float],
        orientation: Iterable[float] | None = None,
        current_joints: Iterable[float] | None = None,
        position_only: bool = False,
    ) -> dict:
        """Compute IK for a target pose."""
        err = self._ensure_solver()
        if err:
            return err

        try:
            pos_arr = np.asarray(position, dtype=float)
            orient_arr = np.asarray(orientation, dtype=float) if orientation is not None else None
            current_arr = np.asarray(current_joints, dtype=float) if current_joints is not None else None
            success, joints = self.solver.solve_ik(
                target_position=pos_arr,
                target_orientation=orient_arr,
                current_joints=current_arr,
                position_only=position_only,
            )
            return {"success": bool(success), "joints": joints.tolist()}
        except Exception as exc:  # noqa: BLE001
            logger.error("solve_ik failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @rpc
    def solve_position_ik(self, position: Iterable[float], current_joints: Iterable[float] | None = None) -> dict:
        """Compute position-only IK (first 3 joints)."""
        err = self._ensure_solver()
        if err:
            return err
        try:
            pos_arr = np.asarray(position, dtype=float)
            current_arr = np.asarray(current_joints, dtype=float) if current_joints is not None else None
            success, joints = self.solver.solve_position_ik(pos_arr, current_arr)
            return {"success": bool(success), "joints": joints.tolist()}
        except Exception as exc:  # noqa: BLE001
            logger.error("solve_position_ik failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @rpc
    def forward_kinematics(self, joints: Iterable[float]) -> dict:
        """Compute FK for provided joints."""
        err = self._ensure_solver()
        if err:
            return err
        try:
            pos, quat = self.solver.get_end_effector_pose(np.asarray(joints, dtype=float))
            return {"success": True, "position": pos.tolist(), "orientation_xyzw": quat.tolist()}
        except Exception as exc:  # noqa: BLE001
            logger.error("forward_kinematics failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @rpc
    def manipulability(self, joints: Iterable[float]) -> dict:
        """Compute manipulability metric."""
        err = self._ensure_solver()
        if err:
            return err
        try:
            value = self.solver.compute_manipulability(np.asarray(joints, dtype=float))
            return {"success": True, "manipulability": value}
        except Exception as exc:  # noqa: BLE001
            logger.error("manipulability failed: %s", exc)
            return {"success": False, "error": str(exc)}
