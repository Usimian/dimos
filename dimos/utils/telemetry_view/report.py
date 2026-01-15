from __future__ import annotations

import json
from pathlib import Path
import webbrowser


def _require_deps() -> tuple[object, object, object, object]:
    """Import pandas/plotly lazily to keep core deps minimal.

    Returns:
        (pd, go, make_subplots, np)
    """
    try:
        import numpy as np  # type: ignore[import-untyped]
        import pandas as pd  # type: ignore[import-untyped]
        import plotly.graph_objects as go  # type: ignore[import-untyped]
        from plotly.subplots import make_subplots  # type: ignore[import-untyped]
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Missing telemetry viewer dependencies. Install with:\n\n"
            "  uv pip install 'dimos[manipulation]'\n"
        ) from e
    return pd, go, make_subplots, np


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _read_csv_or_empty(pd: object, path: Path, columns: list[str]):  # type: ignore[no-untyped-def]
    # pandas is an object here to avoid import at module load time
    if not path.exists():
        return pd.DataFrame(columns=columns)  # type: ignore[attr-defined]
    try:
        df = pd.read_csv(path)  # type: ignore[attr-defined]
        if len(df.index) == 0:
            return pd.DataFrame(columns=columns)  # type: ignore[attr-defined]
        return df
    except Exception:
        return pd.DataFrame(columns=columns)  # type: ignore[attr-defined]


def _downsample_xy(np: object, x, y, max_points: int):  # type: ignore[no-untyped-def]
    if max_points <= 0:
        return x, y
    n = len(x)
    if n <= max_points:
        return x, y
    step = max(1, n // max_points)
    return x[::step], y[::step]


def _metric_base_name(name: str) -> str:
    return name.split("#", 1)[0]


def _pick_default_metrics(metric_names: list[str]) -> list[str]:
    defaults = [
        "/metrics/voxel_map/voxel_count",
        "/metrics/voxel_map/latency_ms",
        "/metrics/voxel_map/publish_ms",
        "/metrics/costmap/latency_ms",
        "/metrics/costmap/calc_ms",
    ]
    present = set(metric_names)
    return [m for m in defaults if m in present]


def _merge_asof_on_trel(pd: object, left, right, value_col: str, out_col: str):  # type: ignore[no-untyped-def]
    if len(right.index) == 0:
        left[out_col] = None
        return left
    l = left.sort_values("t_rel")
    r = right.sort_values("t_rel")[["t_rel", value_col]]
    merged = pd.merge_asof(l, r, on="t_rel", direction="backward")  # type: ignore[attr-defined]
    merged = merged.rename(columns={value_col: out_col})
    return merged


def generate_report(
    *,
    run_dir: Path,
    out_path: Path,
    max_points: int = 5000,
    top_n_topics: int = 10,
    open_browser: bool = True,
) -> Path:
    pd, go, make_subplots, np = _require_deps()

    meta = _read_json(run_dir / "run_meta.json")
    global_config = meta.get("global_config", {}) if isinstance(meta, dict) else {}
    git_sha = meta.get("git_sha", "") if isinstance(meta, dict) else ""

    # Load CSVs (tolerant)
    system = _read_csv_or_empty(
        pd,
        run_dir / "system.csv",
        [
            "ts_wall",
            "ts_mono",
            "t_rel",
            "cpu_percent",
            "load1",
            "load5",
            "load15",
            "mem_total_kb",
            "mem_avail_kb",
            "swap_total_kb",
            "swap_free_kb",
        ],
    )
    process = _read_csv_or_empty(
        pd,
        run_dir / "process.csv",
        ["ts_wall", "ts_mono", "t_rel", "pid", "kind", "cpu_percent", "rss_kb", "cmdline"],
    )
    net = _read_csv_or_empty(
        pd,
        run_dir / "net.csv",
        [
            "ts_wall",
            "ts_mono",
            "t_rel",
            "iface",
            "rx_bytes",
            "tx_bytes",
            "rx_packets",
            "tx_packets",
            "rx_bps",
            "tx_bps",
            "rx_pps",
            "tx_pps",
            "rx_errs",
            "tx_errs",
            "rx_drop",
            "tx_drop",
        ],
    )
    lcm = _read_csv_or_empty(
        pd,
        run_dir / "lcm.csv",
        ["ts_wall", "ts_mono", "t_rel", "topic", "freq_hz", "kbps", "total_bytes"],
    )
    app = _read_csv_or_empty(
        pd,
        run_dir / "app_metrics.csv",
        ["ts_wall", "ts_mono", "t_rel", "metric_name", "value"],
    )
    ping = _read_csv_or_empty(
        pd,
        run_dir / "ping.csv",
        ["ts_wall", "ts_mono", "t_rel", "host", "success", "rtt_ms", "loss_pct"],
    )

    # Normalize / derive
    if len(system.index) > 0:
        system["ram_used_mb"] = (system["mem_total_kb"] - system["mem_avail_kb"]) / 1024.0
        system["swap_used_mb"] = (system["swap_total_kb"] - system["swap_free_kb"]) / 1024.0

    if len(process.index) > 0:
        process["rss_mb"] = process["rss_kb"] / 1024.0

    if len(net.index) > 0:
        net["rx_mbps"] = (net["rx_bps"] * 8.0) / 1e6
        net["tx_mbps"] = (net["tx_bps"] * 8.0) / 1e6

    if len(app.index) > 0:
        app["metric_base"] = app["metric_name"].map(_metric_base_name)

    # Aggregations
    rerun_sum = None
    main_rss = None
    dask_sum = None
    rerun_by_pid = {}
    if len(process.index) > 0:
        rerun_rows = process[process["kind"] == "rerun"]
        if len(rerun_rows.index) > 0:
            rerun_sum = rerun_rows.groupby("t_rel", as_index=False)["rss_mb"].sum().rename(
                columns={"rss_mb": "rerun_rss_mb_sum"}
            )
            for pid, grp in rerun_rows.groupby("pid"):
                g = grp.sort_values("t_rel")
                rerun_by_pid[int(pid)] = g[["t_rel", "rss_mb", "cmdline"]]

        main_rows = process[process["kind"] == "main"].sort_values("t_rel")
        if len(main_rows.index) > 0:
            main_rss = main_rows[["t_rel", "rss_mb"]].rename(columns={"rss_mb": "main_rss_mb"})

        dask_rows = process[process["kind"] == "dask_worker"]
        if len(dask_rows.index) > 0:
            dask_sum = dask_rows.groupby("t_rel", as_index=False)["rss_mb"].sum().rename(
                columns={"rss_mb": "dask_rss_mb_sum"}
            )

    lcm_total = None
    top_topics = []
    if len(lcm.index) > 0:
        lcm_total = lcm[lcm["topic"] == "__total__"].sort_values("t_rel")
        non_total = lcm[lcm["topic"] != "__total__"]
        if len(non_total.index) > 0:
            # Rank by last observed total_bytes (end-of-run proxy)
            last = non_total.sort_values("t_rel").groupby("topic", as_index=False).tail(1)
            last = last.sort_values("total_bytes", ascending=False)
            top_topics = list(last["topic"].head(max(1, int(top_n_topics))).values)

    default_ifaces = []
    if len(net.index) > 0:
        # Choose top interfaces by average total throughput.
        rates = net.groupby("iface", as_index=False).agg({"rx_bps": "mean", "tx_bps": "mean"})
        rates["tot"] = rates["rx_bps"] + rates["tx_bps"]
        rates = rates.sort_values("tot", ascending=False)
        default_ifaces = list(rates["iface"].head(2).values)

    metric_names = []
    default_metrics = []
    if len(app.index) > 0:
        metric_names = sorted(set(app["metric_base"].astype(str).values))
        default_metrics = _pick_default_metrics(metric_names)

    # Figure layout: 6 rows, 2 cols; rows 1-5 span both columns, row 6 has two scatters.
    specs = [
        [{"colspan": 2}, None],
        [{"colspan": 2}, None],
        [{"colspan": 2}, None],
        [{"colspan": 2}, None],
        [{"colspan": 2}, None],
        [{}, {}],
    ]
    fig = make_subplots(
        rows=6,
        cols=2,
        specs=specs,
        shared_xaxes=True,
        vertical_spacing=0.04,
        subplot_titles=[
            "System (CPU / RAM / Swap)",
            "Processes (RSS)",
            "LCM Transport (Totals + Topic)",
            "Network (Selected Interface)",
            "Application Metrics",
            "Correlation: Rerun RSS vs Voxel Count",
            "Correlation: Voxel Latency vs LCM kbps",
        ],
    )

    # Row 1: system
    if len(system.index) > 0:
        x = system["t_rel"].to_numpy()
        fig.add_trace(go.Scatter(x=x, y=system["cpu_percent"], name="CPU %"), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=system["ram_used_mb"], name="RAM used (MB)"), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=system["swap_used_mb"], name="Swap used (MB)"), row=1, col=1)

    if len(ping.index) > 0:
        # Optional overlay: ping rtt on system row (secondary axis would be nicer; keep simple first)
        fig.add_trace(
            go.Scatter(
                x=ping["t_rel"],
                y=ping["rtt_ms"],
                name="Ping RTT (ms)",
                mode="lines",
            ),
            row=1,
            col=1,
        )

    # Row 2: process RSS
    trace_names_rerun_pids = []
    trace_ids_rerun_pids = []
    if rerun_sum is not None:
        x = rerun_sum["t_rel"].to_numpy()
        y = rerun_sum["rerun_rss_mb_sum"].to_numpy()
        x, y = _downsample_xy(np, x, y, max_points)
        fig.add_trace(go.Scatter(x=x, y=y, name="Rerun RSS sum (MB)", line={"width": 3}), row=2, col=1)

    if main_rss is not None:
        x = main_rss["t_rel"].to_numpy()
        y = main_rss["main_rss_mb"].to_numpy()
        x, y = _downsample_xy(np, x, y, max_points)
        fig.add_trace(go.Scatter(x=x, y=y, name="DimOS main RSS (MB)"), row=2, col=1)

    if dask_sum is not None:
        x = dask_sum["t_rel"].to_numpy()
        y = dask_sum["dask_rss_mb_sum"].to_numpy()
        x, y = _downsample_xy(np, x, y, max_points)
        fig.add_trace(go.Scatter(x=x, y=y, name="Dask RSS sum (MB)"), row=2, col=1)

    # Per-rerun PID thin lines (default hidden to reduce clutter)
    for pid, df in sorted(rerun_by_pid.items()):
        x = df["t_rel"].to_numpy()
        y = df["rss_mb"].to_numpy()
        x, y = _downsample_xy(np, x, y, max_points)
        name = f"rerun pid={pid}"
        trace = go.Scatter(x=x, y=y, name=name, visible="legendonly", line={"width": 1})
        fig.add_trace(trace, row=2, col=1)
        trace_names_rerun_pids.append(name)
        trace_ids_rerun_pids.append(len(fig.data) - 1)

    # Row 3: LCM totals + topic selection
    lcm_topic_trace_idxs: dict[str, list[int]] = {}
    if lcm_total is not None and len(lcm_total.index) > 0:
        x = lcm_total["t_rel"].to_numpy()
        fig.add_trace(go.Scatter(x=x, y=lcm_total["kbps"], name="LCM __total__ kbps"), row=3, col=1)
        fig.add_trace(go.Scatter(x=x, y=lcm_total["freq_hz"], name="LCM __total__ Hz"), row=3, col=1)

    # Add per-topic traces for dropdown (hidden by default)
    if len(lcm.index) > 0 and top_topics:
        for t in top_topics:
            rows = lcm[lcm["topic"] == t].sort_values("t_rel")
            if len(rows.index) == 0:
                continue
            x = rows["t_rel"].to_numpy()
            y = rows["kbps"].to_numpy()
            x, y = _downsample_xy(np, x, y, max_points)
            tr = go.Scatter(x=x, y=y, name=f"LCM {t} kbps", visible=False)
            fig.add_trace(tr, row=3, col=1)
            lcm_topic_trace_idxs.setdefault(t, []).append(len(fig.data) - 1)
            y2 = rows["freq_hz"].to_numpy()
            x2, y2 = _downsample_xy(np, x, y2, max_points)
            tr2 = go.Scatter(x=x2, y=y2, name=f"LCM {t} Hz", visible=False)
            fig.add_trace(tr2, row=3, col=1)
            lcm_topic_trace_idxs.setdefault(t, []).append(len(fig.data) - 1)

    # Row 4: net interface selection
    net_iface_trace_idxs = []
    all_ifaces = []
    if len(net.index) > 0:
        all_ifaces = sorted(set(net["iface"].astype(str).values))
        for iface in all_ifaces:
            rows = net[net["iface"] == iface].sort_values("t_rel")
            x = rows["t_rel"].to_numpy()
            rx = rows["rx_mbps"].to_numpy()
            tx = rows["tx_mbps"].to_numpy()
            x, rx = _downsample_xy(np, x, rx, max_points)
            _, tx = _downsample_xy(np, x, tx, max_points)
            default_vis = iface in default_ifaces[:1] if default_ifaces else iface == all_ifaces[0]
            fig.add_trace(go.Scatter(x=x, y=rx, name=f"{iface} rx (Mbps)", visible=default_vis), row=4, col=1)
            net_iface_trace_idxs.append(len(fig.data) - 1)
            fig.add_trace(go.Scatter(x=x, y=tx, name=f"{iface} tx (Mbps)", visible=default_vis), row=4, col=1)
            net_iface_trace_idxs.append(len(fig.data) - 1)

    # Row 5: app metrics (curated default set + dropdown for one-metric focus)
    metric_trace_idxs = []
    metric_groups = {}
    if len(app.index) > 0 and metric_names:
        for m in metric_names:
            rows = app[app["metric_base"] == m].sort_values("t_rel")
            x = rows["t_rel"].to_numpy()
            y = rows["value"].to_numpy()
            x, y = _downsample_xy(np, x, y, max_points)
            vis = m in default_metrics
            fig.add_trace(go.Scatter(x=x, y=y, name=m, visible=vis), row=5, col=1)
            idx = len(fig.data) - 1
            metric_trace_idxs.append(idx)
            metric_groups[m] = idx

    # Correlations row: build as-of joined table on system t_rel
    corr_base = system[["t_rel"]].copy() if len(system.index) > 0 else None
    corr_df = None
    if corr_base is not None and len(corr_base.index) > 0:
        corr_df = corr_base
        # Rerun RSS sum
        if rerun_sum is not None:
            corr_df = _merge_asof_on_trel(pd, corr_df, rerun_sum, "rerun_rss_mb_sum", "rerun_rss_mb_sum")
        else:
            corr_df["rerun_rss_mb_sum"] = None
        # LCM kbps total
        if lcm_total is not None and len(lcm_total.index) > 0:
            tmp = lcm_total[["t_rel", "kbps"]].rename(columns={"kbps": "lcm_total_kbps"})
            corr_df = _merge_asof_on_trel(pd, corr_df, tmp, "lcm_total_kbps", "lcm_total_kbps")
        else:
            corr_df["lcm_total_kbps"] = None
        # App metrics: voxel_count, voxel_latency
        if len(app.index) > 0:
            for m, col in [
                ("/metrics/voxel_map/voxel_count", "voxel_count"),
                ("/metrics/voxel_map/latency_ms", "voxel_latency_ms"),
            ]:
                rows = app[app["metric_base"] == m][["t_rel", "value"]].rename(columns={"value": col})
                corr_df = _merge_asof_on_trel(pd, corr_df, rows, col, col)
        else:
            corr_df["voxel_count"] = None
            corr_df["voxel_latency_ms"] = None

    if corr_df is not None:
        # Scatter 1
        fig.add_trace(
            go.Scatter(
                x=corr_df.get("voxel_count"),
                y=corr_df.get("rerun_rss_mb_sum"),
                mode="markers",
                name="Rerun RSS vs voxel_count",
            ),
            row=6,
            col=1,
        )
        # Scatter 2
        fig.add_trace(
            go.Scatter(
                x=corr_df.get("lcm_total_kbps"),
                y=corr_df.get("voxel_latency_ms"),
                mode="markers",
                name="voxel_latency vs lcm_kbps",
            ),
            row=6,
            col=2,
        )

    # Dropdown menus
    updatemenus = []

    # LCM topic dropdown (toggles per-topic traces on row3)
    if top_topics and lcm_topic_trace_idxs:
        buttons = []
        # baseline: hide all per-topic traces
        visible = [True] * len(fig.data)
        for idxs in lcm_topic_trace_idxs.values():
            for idx in idxs:
                visible[idx] = False
        buttons.append({"label": "__total__ only", "method": "update", "args": [{"visible": visible}]})

        # per topic
        for i, t in enumerate(top_topics):
            vis2 = visible.copy()
            for idx in lcm_topic_trace_idxs.get(t, []):
                vis2[idx] = True
            buttons.append({"label": t, "method": "update", "args": [{"visible": vis2}]})

        updatemenus.append(
            {
                "buttons": buttons,
                "direction": "down",
                "showactive": True,
                "x": 1.0,
                "xanchor": "right",
                "y": 0.78,
                "yanchor": "top",
            }
        )

    # Net iface dropdown (toggles row4 traces)
    if all_ifaces and net_iface_trace_idxs:
        buttons = []
        # there are 2 traces per iface in insertion order
        for i, iface in enumerate(all_ifaces):
            vis = [d.visible for d in fig.data]
            for idx in net_iface_trace_idxs:
                vis[idx] = False
            base = i * 2
            if base + 1 < len(net_iface_trace_idxs):
                vis[net_iface_trace_idxs[base]] = True
                vis[net_iface_trace_idxs[base + 1]] = True
            buttons.append({"label": iface, "method": "update", "args": [{"visible": vis}]})
        updatemenus.append(
            {
                "buttons": buttons,
                "direction": "down",
                "showactive": True,
                "x": 1.0,
                "xanchor": "right",
                "y": 0.62,
                "yanchor": "top",
            }
        )

    # App metrics dropdown: show defaults or focus on one metric
    if metric_groups:
        buttons = []
        base_vis = [d.visible for d in fig.data]
        # Ensure base_vis corresponds to default-metrics visibility as added
        buttons.append({"label": "default set", "method": "update", "args": [{"visible": base_vis}]})
        for m, idx in metric_groups.items():
            vis = base_vis.copy()
            # hide all metric traces then show just one
            for j in metric_trace_idxs:
                vis[j] = False
            vis[idx] = True
            buttons.append({"label": m, "method": "update", "args": [{"visible": vis}]})
        updatemenus.append(
            {
                "buttons": buttons,
                "direction": "down",
                "showactive": True,
                "x": 1.0,
                "xanchor": "right",
                "y": 0.46,
                "yanchor": "top",
            }
        )

    # Title / annotation
    run_id = run_dir.name
    robot_model = global_config.get("robot_model", "")
    viewer_backend = global_config.get("viewer_backend", "")
    telemetry_rate_hz = global_config.get("telemetry_rate_hz", "")
    title = f"DimOS Telemetry Report — {run_id}"
    subtitle = f"robot_model={robot_model} viewer_backend={viewer_backend} telemetry_rate_hz={telemetry_rate_hz} git_sha={git_sha}"

    fig.update_layout(
        title={"text": f"{title}<br><sup>{subtitle}</sup>"},
        hovermode="x unified",
        updatemenus=updatemenus,
        height=1400,
        legend={"orientation": "h"},
        margin={"l": 60, "r": 40, "t": 90, "b": 60},
    )
    fig.update_xaxes(title_text="t_rel (s)", row=5, col=1)
    fig.update_xaxes(title_text="t_rel (s)", row=4, col=1)
    fig.update_xaxes(rangeslider={"visible": True}, row=5, col=1)
    fig.update_xaxes(title_text="voxel_count", row=6, col=1)
    fig.update_yaxes(title_text="rerun_rss_mb_sum", row=6, col=1)
    fig.update_xaxes(title_text="lcm_total_kbps", row=6, col=2)
    fig.update_yaxes(title_text="voxel_latency_ms", row=6, col=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out_path), include_plotlyjs="cdn", full_html=True)

    if open_browser:
        try:
            webbrowser.open_new_tab(out_path.resolve().as_uri())
        except Exception:
            pass

    return out_path

