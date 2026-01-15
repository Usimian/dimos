from __future__ import annotations

from pathlib import Path

from dimos.constants import DIMOS_LOG_DIR


def find_latest_run_dir(base: Path | None = None) -> Path:
    runs_dir = (base or (DIMOS_LOG_DIR / "runs")).expanduser().resolve()
    if not runs_dir.exists():
        raise FileNotFoundError(f"No runs directory found at {runs_dir}")
    candidates = [p for p in runs_dir.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No run directories found under {runs_dir}")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def resolve_run_dir(run_dir: Path | None, *, latest: bool) -> Path:
    if latest:
        return find_latest_run_dir()
    if run_dir is None:
        raise ValueError("run_dir must be provided unless --latest is set")
    return Path(run_dir).expanduser().resolve()


def ensure_run_dir_has_data(run_dir: Path) -> None:
    if not run_dir.exists():
        raise FileNotFoundError(f"Run dir does not exist: {run_dir}")
    if not run_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {run_dir}")

    has_any = False
    for name in [
        "run_meta.json",
        "system.csv",
        "process.csv",
        "net.csv",
        "lcm.csv",
        "app_metrics.csv",
        "ping.csv",
        "gpu.csv",
    ]:
        if (run_dir / name).exists():
            has_any = True
            break
    if not has_any:
        raise FileNotFoundError(f"No telemetry files found in {run_dir}")

