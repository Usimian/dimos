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

from datetime import datetime, timezone
from enum import Enum
import inspect
import io
import os
from pathlib import Path
import sys
import threading
from typing import Any, Optional, get_args, get_origin

import typer

from dimos.constants import DIMOS_LOG_DIR
from dimos.core.blueprints import autoconnect
from dimos.core.global_config import GlobalConfig
from dimos.protocol import pubsub
from dimos.robot.all_blueprints import all_blueprints, get_blueprint_by_name, get_module_by_name
from dimos.robot.cli.topic import topic_echo, topic_send
from dimos.utils.logging_config import setup_exception_handler

RobotType = Enum("RobotType", {key.replace("-", "_").upper(): key for key in all_blueprints.keys()})  # type: ignore[misc]

main = typer.Typer(
    help="Dimensional CLI",
    no_args_is_help=True,
)

telemetry_app = typer.Typer(help="Telemetry tools")
main.add_typer(telemetry_app, name="telemetry")

_console_tee_lock = threading.Lock()


class _TeeTextIO(io.TextIOBase):
    """Write-through tee for text streams (stdout/stderr)."""

    def __init__(self, *streams: io.TextIOBase) -> None:
        super().__init__()
        self._streams = streams

    def write(self, s: str) -> int:  # type: ignore[override]
        with _console_tee_lock:
            for st in self._streams:
                try:
                    st.write(s)
                except Exception:
                    pass
            for st in self._streams:
                try:
                    st.flush()
                except Exception:
                    pass
        return len(s)

    def flush(self) -> None:  # type: ignore[override]
        with _console_tee_lock:
            for st in self._streams:
                try:
                    st.flush()
                except Exception:
                    pass

    def isatty(self) -> bool:  # type: ignore[override]
        # Preserve tty behavior for downstream libs that detect TTY.
        try:
            return self._streams[0].isatty()
        except Exception:
            return False


def _ensure_run_dir(provided: str | None) -> Path:
    if provided:
        p = Path(provided)
        p.mkdir(parents=True, exist_ok=True)
        return p
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pid = os.getpid()
    p = DIMOS_LOG_DIR / "runs" / f"{ts}_{pid}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_dynamic_callback():  # type: ignore[no-untyped-def]
    fields = GlobalConfig.model_fields

    # Build the function signature dynamically
    params = [
        inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=typer.Context),
    ]

    # Create parameters for each field in GlobalConfig
    for field_name, field_info in fields.items():
        field_type = field_info.annotation

        # Handle Optional types
        # Check for Optional/Union with None
        if get_origin(field_type) is type(Optional[str]):  # noqa: UP045
            inner_types = get_args(field_type)
            if len(inner_types) == 2 and type(None) in inner_types:
                # It's Optional[T], get the actual type T
                actual_type = next(t for t in inner_types if t != type(None))
            else:
                actual_type = field_type
        else:
            actual_type = field_type

        # Convert field name from snake_case to kebab-case for CLI
        cli_option_name = field_name.replace("_", "-")

        # Special handling for boolean fields
        if actual_type is bool:
            # For boolean fields, create --flag/--no-flag pattern
            param = inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=typer.Option(
                    None,  # None means use the model's default if not provided
                    f"--{cli_option_name}/--no-{cli_option_name}",
                    help=f"Override {field_name} in GlobalConfig",
                ),
                annotation=Optional[bool],  # noqa: UP045
            )
        else:
            # For non-boolean fields, use regular option
            param = inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=typer.Option(
                    None,  # None means use the model's default if not provided
                    f"--{cli_option_name}",
                    help=f"Override {field_name} in GlobalConfig",
                ),
                annotation=Optional[actual_type],  # noqa: UP045
            )
        params.append(param)

    def callback(**kwargs) -> None:  # type: ignore[no-untyped-def]
        ctx = kwargs.pop("ctx")
        ctx.obj = {k: v for k, v in kwargs.items() if v is not None}

    callback.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]

    return callback


main.callback()(create_dynamic_callback())  # type: ignore[no-untyped-call]


@main.command()
def run(
    ctx: typer.Context,
    robot_type: RobotType = typer.Argument(..., help="Type of robot to run"),
    extra_modules: list[str] = typer.Option(  # type: ignore[valid-type]
        [], "--extra-module", help="Extra modules to add to the blueprint"
    ),
    telemetry: bool | None = typer.Option(
        None,
        "--telemetry/--no-telemetry",
        help="Enable run-scoped telemetry logging (CSV + JSONL) under logs/runs/<run_id>/",
    ),
    telemetry_rate_hz: float | None = typer.Option(
        None,
        "--telemetry-rate-hz",
        help="Telemetry sampling rate (Hz) when --telemetry is enabled.",
    ),
    telemetry_run_dir: str | None = typer.Option(
        None,
        "--telemetry-run-dir",
        help="Override telemetry output dir for this run (default: logs/runs/<run_id>/).",
    ),
) -> None:
    """Start a robot blueprint"""
    setup_exception_handler()

    cli_config_overrides: dict[str, Any] = ctx.obj
    if telemetry is not None:
        cli_config_overrides["telemetry_enabled"] = telemetry
    if telemetry_rate_hz is not None:
        cli_config_overrides["telemetry_rate_hz"] = telemetry_rate_hz
    if telemetry_run_dir is not None:
        cli_config_overrides["telemetry_run_dir"] = telemetry_run_dir

    telemetry_enabled = bool(cli_config_overrides.get("telemetry_enabled", False))

    # When telemetry is enabled, also set common debug env vars and tee stdout/stderr to disk.
    tee_file: io.TextIOWrapper | None = None
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    if telemetry_enabled:
        run_dir = _ensure_run_dir(cli_config_overrides.get("telemetry_run_dir"))
        cli_config_overrides["telemetry_run_dir"] = str(run_dir)

        # Requested: set these automatically when running with --telemetry.
        os.environ["DIMOS_LOG_LEVEL"] = "DEBUG"
        os.environ["RERUN_SAVE"] = "1"

        try:
            tee_path = run_dir / "console_output.log"
            tee_file = open(tee_path, "a", buffering=1, encoding="utf-8")
            sys.stdout = _TeeTextIO(orig_stdout, tee_file)
            sys.stderr = _TeeTextIO(orig_stderr, tee_file)
            print(f"[telemetry] console output -> {tee_path}")
        except Exception:
            tee_file = None

    pubsub.lcm.autoconf()  # type: ignore[attr-defined]
    blueprint = get_blueprint_by_name(robot_type.value)

    if extra_modules:
        loaded_modules = [get_module_by_name(mod_name) for mod_name in extra_modules]  # type: ignore[attr-defined]
        blueprint = autoconnect(blueprint, *loaded_modules)

    try:
        dimos = blueprint.build(cli_config_overrides=cli_config_overrides)
        dimos.loop()
    finally:
        # Restore stdout/stderr and close tee file.
        if telemetry_enabled:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            try:
                if tee_file is not None:
                    tee_file.flush()
                    tee_file.close()
            except Exception:
                pass


@telemetry_app.command()
def view(
    run_dir: Path | None = typer.Argument(
        None,
        help="Telemetry run directory (e.g. logs/runs/<run_id>). Omit with --latest.",
    ),
    latest: bool = typer.Option(False, "--latest", help="Use latest run under logs/runs/."),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Output HTML path (default: <run_dir>/report.html).",
    ),
    no_open: bool = typer.Option(False, "--no-open", help="Do not auto-open the report in a browser."),
    max_points: int = typer.Option(
        5000,
        "--max-points",
        help="Max points per series to keep Plotly responsive (stride downsample).",
    ),
    top_n_topics: int = typer.Option(
        10,
        "--top-n-topics",
        help="Top N LCM topics to include for the topic dropdown (ranked by total_bytes).",
    ),
) -> None:
    """Generate an interactive Plotly HTML report for a telemetry run."""
    try:
        from dimos.utils.telemetry_view.io import ensure_run_dir_has_data, resolve_run_dir
        from dimos.utils.telemetry_view.report import generate_report

        rd = resolve_run_dir(run_dir, latest=latest)
        ensure_run_dir_has_data(rd)

        out_path = out or (rd / "report.html")
        p = generate_report(
            run_dir=rd,
            out_path=out_path,
            max_points=max_points,
            top_n_topics=top_n_topics,
            open_browser=not no_open,
        )
        typer.echo(f"Wrote report: {p}")
    except Exception as e:
        typer.echo(str(e))
        raise typer.Exit(code=1) from e


@main.command()
def show_config(ctx: typer.Context) -> None:
    """Show current config settings and their values."""
    cli_config_overrides: dict[str, Any] = ctx.obj
    config = GlobalConfig().model_copy(update=cli_config_overrides)

    for field_name, value in config.model_dump().items():
        typer.echo(f"{field_name}: {value}")


@main.command()
def list() -> None:
    """List all available blueprints."""
    blueprints = [name for name in all_blueprints.keys() if not name.startswith("demo-")]
    for blueprint_name in sorted(blueprints):
        typer.echo(blueprint_name)


@main.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def lcmspy(ctx: typer.Context) -> None:
    """LCM spy tool for monitoring LCM messages."""
    from dimos.utils.cli.lcmspy.run_lcmspy import main as lcmspy_main

    sys.argv = ["lcmspy", *ctx.args]
    lcmspy_main()


@main.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def skillspy(ctx: typer.Context) -> None:
    """Skills spy tool for monitoring skills."""
    from dimos.utils.cli.skillspy.skillspy import main as skillspy_main

    sys.argv = ["skillspy", *ctx.args]
    skillspy_main()


@main.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def agentspy(ctx: typer.Context) -> None:
    """Agent spy tool for monitoring agents."""
    from dimos.utils.cli.agentspy.agentspy import main as agentspy_main

    sys.argv = ["agentspy", *ctx.args]
    agentspy_main()


@main.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def humancli(ctx: typer.Context) -> None:
    """Interface interacting with agents."""
    from dimos.utils.cli.human.humanclianim import main as humancli_main

    sys.argv = ["humancli", *ctx.args]
    humancli_main()


topic_app = typer.Typer(help="Topic commands for pub/sub")
main.add_typer(topic_app, name="topic")


@topic_app.command()
def echo(
    topic: str = typer.Argument(..., help="Topic name to listen on (e.g., /goal_request)"),
    type_name: str | None = typer.Argument(
        None,
        help="Optional message type (e.g., PoseStamped). If omitted, infer from '/topic#pkg.Msg'.",
    ),
) -> None:
    topic_echo(topic, type_name)


@topic_app.command()
def send(
    topic: str = typer.Argument(..., help="Topic name to send to (e.g., /goal_request)"),
    message_expr: str = typer.Argument(..., help="Python expression for the message"),
) -> None:
    topic_send(topic, message_expr)


if __name__ == "__main__":
    main()
