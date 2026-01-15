# Telemetry Logging (run-scoped CSVs)

DimOS can optionally record **run-scoped telemetry** (system, process, network, LCM traffic, and app metrics) to CSV files for postmortem performance analysis.

This is designed for investigations like **Rerun memory growth**, CPU saturation, transport bottlenecks, or network issues when connected to a real robot.

## Enable telemetry

Run any blueprint with `--telemetry`:

```bash
dimos run unitree-go2 --telemetry
```

Optional overrides:

```bash
dimos run unitree-go2 --telemetry --telemetry-rate-hz 2
dimos run unitree-go2 --telemetry --telemetry-run-dir /tmp/dimos_telemetry/my_run
```

## Integrated debug defaults when telemetry is enabled

When `--telemetry` is enabled, `dimos run` also:

- sets `DIMOS_LOG_LEVEL=DEBUG` for the current process
- sets `RERUN_SAVE=1` for the current process
- tees all console output (stdout/stderr) to `logs/runs/<run_id>/console_output.log`

## Generate an interactive HTML report

To view a run as an interactive Plotly HTML report, install the viewer deps (for now we reuse the existing extra):

```bash
uv pip install 'dimos[manipulation]'
```

Then generate/open the report:

```bash
dimos telemetry view logs/runs/<run_id>
```

Or for the most recent run:

```bash
dimos telemetry view --latest
```

This writes `report.html` into the run directory and auto-opens it in your browser. Use `--no-open` to disable auto-open.

## Output directory layout

When enabled, DimOS creates a new run directory under:

- `logs/runs/<run_id>/`

and writes:

- `run_meta.json`: run metadata (start time + GlobalConfig dump + best-effort git sha)\n
- `system.csv`: CPU/load/memory samples\n
- `process.csv`: per-PID CPU/RSS samples (main + dask workers + best-effort rerun processes)\n
- `net.csv`: per-interface counters and derived rates\n
- `ping.csv`: ping samples to `GlobalConfig.robot_ip` (if set)\n
- `gpu.csv`: best-effort samples from `nvidia-smi` (if available)\n
- `lcm.csv`: LCMSpy-derived topic frequency/bandwidth/total bytes\n
- `app_metrics.csv`: `/metrics/*` Float32 time series (including voxel/costmap metrics)\n

Separately, regular DimOS structured logs continue to go to:

- `logs/dimos_<timestamp>_<pid>.jsonl`

## Timestamps (important)

Every CSV row includes:

- `ts_wall`: epoch seconds (`time.time()`)\n
- `ts_mono`: monotonic seconds (`time.monotonic()`)\n
- `t_rel`: seconds since run start (monotonic)\n

For correlation and plotting, prefer `t_rel` (it never jumps due to NTP/clock adjustments).

## Notes

- Telemetry is started/stopped automatically with the run lifecycle (no blueprint wiring).\n
- Telemetry is **best-effort**: failures to sample one subsystem (e.g., missing `nvidia-smi`) should not crash a run.\n
