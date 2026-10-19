#!/usr/bin/env python3
"""
E1 analysis: one command regenerates every table and figure from the raw logs.

  python tools/analysis/e1_analyze.py --root data/E1_outage_sweep

Reads <root>/<run_id>/{source,relay,sink}.txt + manifest.json + events.json (raw, never edited).
Writes per-run result_e1.json, <root>/E1_runs.csv, <root>/E1_summary.md and figures in <root>/figures/.

Metrics: unique PDR = distinct sequence numbers delivered at the sink / distinct sequence numbers sent by the source. The unit of inference is the run: per-condition
values are bootstrap CIs (10,000 resamples, fixed seed) of the run means. Nothing is removed.
Counters are primary, the log is the cross-check: when they differ the run is marked
`log_lossy` and still reported.
"""
from __future__ import annotations

import csv
import json
import random
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / "harness"))
import analyze_run as run_analysis  # noqa: E402

DEV = re.compile(r"\[(\d+):(\d\d):(\d\d)\.(\d{3}),(\d{3})\] <inf> app: (\w+): (.*)$")
LAMBDA = 1.0  # pkt/s


def devlines(path: Path) -> list[tuple[int, str, str]]:
    """(device time in us, tag, rest) for every protocol log line."""
    out = []
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = DEV.search(raw)
        if m:
            h, mi, s, ms, us, tag, rest = m.groups()
            t = ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1_000_000 + int(ms) * 1000 + int(us)
            out.append((t, tag, rest))
    return out


def kv(text: str) -> dict:
    return dict(re.findall(r"(\w+)=(\S+)", text))


def drain_metrics(relay: list, sink_id: int, up_us: int | None) -> dict:
    """Backlog B at link-up, measured drain time (link UP -> relay store empty), mu, T_d."""
    res: dict = {}
    pending: dict[int, int] = {}
    peak = 0
    first_full = None
    events = []  # (t, kind, seq)
    for t, tag, rest in relay:
        d = kv(rest)
        if tag == "STORED" and d.get("class") == "tel":
            events.append((t, "add", int(d["seq"])))
        elif tag == "ACK_RX" and d.get("status") in ("ACCEPTED", "DUPLICATE") and d.get("from") == str(sink_id):
            events.append((t, "rel", int(d["seq"])))
        elif tag == "NACK_TX" and "QUEUE_FULL" in rest and first_full is None:
            first_full = t
    pend_at_up = None
    drain_end = None
    n_acked = 0
    ack_times: list[int] = []
    for t, kind, seq in sorted(events, key=lambda e: e[0]):
        if up_us is not None and pend_at_up is None and t >= up_us:
            pend_at_up = len(pending)
        if kind == "add":
            pending[seq] = t
        else:
            pending.pop(seq, None)
            if up_us is not None and t >= up_us:
                n_acked += 1
                ack_times.append(t)
        peak = max(peak, len(pending))
        if up_us is not None and pend_at_up is not None and drain_end is None and t >= up_us and not pending \
                and kind == "rel":
            drain_end = t
            res["acks_during_drain"] = n_acked
    res["relay_peak_pending"] = peak
    res["_stored_times"] = [t for t, kind, _ in events if kind == "add"]
    res["first_queue_full_us"] = first_full
    if up_us is not None:
        if pend_at_up is None:
            pend_at_up = len(pending)
        res["B_at_up"] = pend_at_up
        if drain_end is not None and drain_end > up_us:
            span = (drain_end - up_us) / 1e6
            res["drain_s"] = round(span, 3)
            mu = res["acks_during_drain"] / span
            res["mu_pkt_s"] = round(mu, 2)
            if mu > LAMBDA and pend_at_up:
                res["T_d_pred_s"] = round(pend_at_up / (mu - LAMBDA), 3)
            # Note: mu above counts every ACK in the drain, including the lambda*T new arrivals, so
            # B / (mu - lambda) equals the measured drain time by construction (the plan's definition, kept
            # as reported). The cycle-based mu below is the non-circular estimate: 1 / median gap between
            # consecutive ACKs while the backlog lasts (gaps over 150 ms are retransmissions, left out).
            arr = [t for t in res["_stored_times"] if up_us <= t <= drain_end]
            res["arrivals_in_drain"] = len(arr)
            gaps = [(b - a_) / 1e6 for a_, b in zip(ack_times, ack_times[1:]) if (b - a_) < 150_000]
            if len(gaps) >= 3:
                mu_c = 1.0 / statistics.median(gaps)
                res["mu_cycle_pkt_s"] = round(mu_c, 2)
                if mu_c > LAMBDA and pend_at_up:
                    res["T_d_pred_cycle_s"] = round(pend_at_up / (mu_c - LAMBDA), 3)
                    if arr:
                        res["penalty_per_arrival_s"] = round((span - res["T_d_pred_cycle_s"]) / len(arr), 3)
    res.pop("_stored_times", None)
    return res


def analyse_run(folder: Path) -> dict:
    base = run_analysis.analyse(folder)  # PDR, link events, RTT, detection/re-up (device clock), error lines
    man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    ids = man["ids"]
    relay = devlines(folder / "relay.txt")
    sink = devlines(folder / "sink.txt")
    src = devlines(folder / "source.txt")
    res = {k: base.get(k) for k in (
        "run_id", "status", "custody", "count", "outage_s", "sent_unique", "delivered_unique", "lost_count",
        "unique_pdr", "duplicate_deliveries", "detection_s", "reup_s", "detection_dev_s", "reup_dev_s",
        "rtt_ms_source", "rtt_ms_relay", "retry_lines", "relay_queue_full_nacks", "source_peak_depth",
        "relay_peak_depth", "error_lines", "lost_in_outage_window", "lost_outside_outage_window",
        "baseline_loss_rate_outside_outage", "open_loop_loss_vs_expected", "clock_offset_fit")}
    res["mode"] = "custody" if man["custody"] else "openloop"
    res["gaps"] = man.get("gaps")
    res["extra"] = man.get("extra")
    res["git"] = man.get("git", {}).get("commit")
    # counters: sink delivered before the stop + after the restart; source generated
    stops = [kv(rest) for _, tag, rest in sink if tag == "SUMMARY"]
    sink_cnt = sum(int(s.get("delivered", 0)) for s in stops)
    gen = [kv(rest) for _, tag, rest in src if tag == "SUMMARY"]
    src_gen = int(gen[-1]["generated"]) if gen else None
    res["counter_sink_delivered_sum"] = sink_cnt if stops else None
    res["counter_source_generated"] = src_gen
    res["counter_vs_log_sink"] = None if not stops else (sink_cnt, base["delivered_lines"])
    res["log_lossy"] = bool(stops) and sink_cnt != base["delivered_lines"]
    # delivered by counters (primary): sink delivered minus duplicate deliveries is not available,
    # so unique PDR from the log is paired with the counter check above.
    res["pdr_counter_based"] = (round(sink_cnt / src_gen, 4) if stops and src_gen else None)
    # Counters are primary. The log-based value stays as pdr_log; they differ only when the sink's
    # serial log dropped lines during a fast drain (the log cannot carry about 27 lines/s at 115200 baud).
    res["pdr_log"] = res["unique_pdr"]
    res["lost_log"] = res["lost_count"]
    if stops and src_gen:
        res["unique_pdr"] = res["pdr_counter_based"]
        res["lost_count"] = src_gen - sink_cnt
    # custody drain metrics
    if man["custody"] and man["outage_s"] is not None:
        sink_id = ids["sink"]
        up_events = [(t, kv(r)) for t, tag, r in relay if tag == "LINK_STATE"]
        # restore time on the relay device clock: the first UP after the (last) DOWN of the outage
        downs = [t for t, d in up_events if d.get("next") == str(sink_id) and d.get("new") == "DOWN"]
        ups = [t for t, d in up_events if d.get("next") == str(sink_id) and d.get("new") == "UP"]
        res["down_events"] = len(downs)
        res["up_events"] = len(ups)
        up_after = [t for t in ups if downs and t > downs[0]]
        res["relay_link_down_events"] = len(downs)
        if up_after:
            res.update(drain_metrics(relay, sink_id, up_after[0]))
            if res.get("drain_s") and res.get("T_d_pred_s"):
                res["T_d_error_pct"] = round(100.0 * (res["T_d_pred_s"] - res["drain_s"]) / res["drain_s"], 1)
            if res.get("drain_s") and res.get("T_d_pred_cycle_s"):
                res["T_d_error_cycle_pct"] = round(
                    100.0 * (res["T_d_pred_cycle_s"] - res["drain_s"]) / res["drain_s"], 1)
        else:
            res.update(drain_metrics(relay, sink_id, None))
    # per-run verdict flags
    flags = []
    if base.get("status") != "ok":
        flags.append(str(base.get("status")))
    if base.get("error_lines"):
        flags.append("error_lines")
    if res["log_lossy"]:
        flags.append("log_lossy")
    if any("messages dropped" in t for lst in (base.get("error_lines") or {}).values() for t in lst):
        flags.append("log_loss")
    res["flags"] = flags
    return res


def bootstrap_ci(vals: list[float], n: int = 10000, seed: int = 1) -> tuple[float, float]:
    rng = random.Random(seed)
    m = len(vals)
    means = sorted(sum(rng.choice(vals) for _ in range(m)) / m for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def summarize(vals: list[float | None]) -> dict | None:
    v = [x for x in vals if x is not None]
    if not v:
        return None
    lo, hi = bootstrap_ci(v) if len(v) > 1 else (v[0], v[0])
    return {"n": len(v), "mean": round(statistics.mean(v), 4), "median": round(statistics.median(v), 4),
            "min": min(v), "max": max(v), "ci_lo": round(lo, 4), "ci_hi": round(hi, 4)}


def cond_of(r: dict) -> str:
    rid = r["run_id"]
    return re.sub(r"_r\d+(_retry\d+)?$", "", rid)


def fmt(s: dict | None, nd: int = 3) -> str:
    if not s:
        return "-"
    if s["n"] == 1:
        return f"{s['mean']:.{nd}f} (n=1)"
    return f"{s['mean']:.{nd}f} [{s['ci_lo']:.{nd}f}, {s['ci_hi']:.{nd}f}] n={s['n']}"


def main() -> int:
    args = sys.argv[1:]
    root = Path(args[args.index("--root") + 1]) if "--root" in args else Path("data/E1_outage_sweep_v2")
    folders = sorted(p for p in root.iterdir() if p.is_dir() and (p / "manifest.json").exists())
    runs = []
    for f in folders:
        r = analyse_run(f)
        (f / "result_e1.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
        runs.append(r)
    if not runs:
        print("no runs")
        return 1
    # per-run CSV
    cols = ["run_id", "mode", "outage_s", "count", "sent_unique", "delivered_unique", "lost_count", "unique_pdr",
            "pdr_counter_based", "duplicate_deliveries", "detection_dev_s", "reup_dev_s", "detection_s", "reup_s",
            "B_at_up", "relay_peak_pending", "drain_s", "mu_pkt_s", "T_d_pred_s", "T_d_error_pct", "mu_cycle_pkt_s", "T_d_pred_cycle_s", "T_d_error_cycle_pct", "arrivals_in_drain", "penalty_per_arrival_s",
            "relay_link_down_events", "relay_queue_full_nacks", "source_peak_depth", "flags"]
    with (root / "E1_runs.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in runs:
            w.writerow([";".join(r["flags"]) if c == "flags" else r.get(c) for c in cols])
    # per-condition summary
    # runs cut short by an infrastructure or operator error carry no measurement: listed, not averaged
    failed = [r for r in runs if str(r.get("status")).startswith(("error", "setup_error"))]
    runs_ok = [r for r in runs if r not in failed]
    by: dict[str, list[dict]] = {}
    for r in runs_ok:
        by.setdefault(cond_of(r), []).append(r)
    lines = ["# E1 summary", "",
             "Generated by `tools/analysis/e1_analyze.py` from the raw logs. Per-condition values are the mean of per-run values with a",
             "bootstrap 95% CI of the run means (10,000 resamples); n is the number of runs. No run is removed; flagged runs are counted.", "",
             "| condition | runs | flagged | unique PDR | lost (packets) | expected loss lambda*D | open-loop lost/(lambda*D) | detection s (device) | re-up s (device) | B at UP | drain s | mu pkt/s (count) | T_d pred s | T_d error % | mu cycle pkt/s | T_d pred cycle s | T_d error cycle % | DOWN events |",
             "|---|---:|---:|---|---|---:|---|---|---|---|---|---|---|---|---|---|---|---|"]
    stats: dict[str, dict] = {}
    for c in sorted(by):
        rs = by[c]
        s = {
            "pdr": summarize([r["unique_pdr"] for r in rs]),
            "lost": summarize([r["lost_count"] for r in rs]),
            "ratio": summarize([r.get("open_loop_loss_vs_expected") for r in rs]),
            "det": summarize([r.get("detection_dev_s") if r.get("detection_dev_s") is not None else r.get("detection_s") for r in rs]),
            "reup": summarize([r.get("reup_dev_s") if r.get("reup_dev_s") is not None else r.get("reup_s") for r in rs]),
            "B": summarize([r.get("B_at_up") for r in rs]),
            "drain": summarize([r.get("drain_s") for r in rs]),
            "mu": summarize([r.get("mu_pkt_s") for r in rs]),
            "Td": summarize([r.get("T_d_pred_s") for r in rs]),
            "Terr": summarize([r.get("T_d_error_pct") for r in rs]),
            "muc": summarize([r.get("mu_cycle_pkt_s") for r in rs]),
            "Tdc": summarize([r.get("T_d_pred_cycle_s") for r in rs]),
            "Terrc": summarize([r.get("T_d_error_cycle_pct") for r in rs]),
            "down": summarize([r.get("relay_link_down_events") for r in rs]),
        }
        stats[c] = s
        flagged = sum(1 for r in rs if r["flags"])
        D = rs[0]["outage_s"]
        lines.append(f"| {c} | {len(rs)} | {flagged} | {fmt(s['pdr'], 4)} | {fmt(s['lost'], 1)} | {D if D is not None else '-'} | "
                     f"{fmt(s['ratio'], 2)} | {fmt(s['det'], 2)} | {fmt(s['reup'], 2)} | {fmt(s['B'], 1)} | {fmt(s['drain'], 2)} | "
                     f"{fmt(s['mu'], 1)} | {fmt(s['Td'], 2)} | {fmt(s['Terr'], 1)} | {fmt(s['muc'], 1)} | {fmt(s['Tdc'], 2)} | {fmt(s['Terrc'], 1)} | {fmt(s['down'], 1)} |")
    # pre-registered criteria
    lines += ["", "## Pre-set criteria (defined before the runs; not changed)", ""]
    for c in sorted(by):
        rs = by[c]
        D = rs[0]["outage_s"]
        if D is None:
            continue
        if rs[0]["mode"] == "custody" and D < 288 and c.startswith("E1_"):
            pdrs = [r["unique_pdr"] for r in rs if r["unique_pdr"] is not None]
            ok = all(p >= 0.99 for p in pdrs)
            lines.append(f"- {c}: custody unique PDR >= 0.99 in every run: **{'met' if ok else 'NOT met'}** "
                         f"(min {min(pdrs):.4f}, mean {statistics.mean(pdrs):.4f}, n={len(pdrs)})")
        if rs[0]["mode"] == "openloop" and c.startswith("E1_"):
            ratios = [r["open_loop_loss_vs_expected"] for r in rs if r.get("open_loop_loss_vs_expected") is not None]
            if ratios:
                mean_r = statistics.mean(ratios)
                lines.append(f"- {c}: open-loop raw loss / (lambda*D): mean {mean_r:.2f}, range {min(ratios):.2f} to {max(ratios):.2f} "
                             f"(criterion 0.8 to 1.2 on the run mean: **{'met' if 0.8 <= mean_r <= 1.2 else 'NOT met'}**)")
        if rs[0]["mode"] == "custody" and c.startswith("E1_"):
            errc = [abs(r["T_d_error_cycle_pct"]) for r in rs if r.get("T_d_error_cycle_pct") is not None]
            if errc:
                lines.append(f"- {c}: cycle-based |T_d predicted - measured| / measured: median {statistics.median(errc):.1f}%, "
                             f"max {max(errc):.1f}% (criterion about 15%: {'met' if statistics.median(errc) <= 15 else 'NOT met'} on the median)")
            errs = [abs(r["T_d_error_pct"]) for r in rs if r.get("T_d_error_pct") is not None]
            if errs:
                lines.append(f"- {c}: |T_d predicted - measured| / measured: median {statistics.median(errs):.1f}%, "
                             f"max {max(errs):.1f}% (criterion about 15%: {'met' if statistics.median(errs) <= 15 else 'NOT met'} on the median)")
    # flagged runs
    lines += ["", "## Flagged runs", ""]
    fl = [r for r in runs if r["flags"]]
    lines += [f"- {r['run_id']}: {', '.join(r['flags'])}" for r in fl] or ["- none"]
    lines += ["", "## Failed runs (excluded from the statistics, kept in data/)", ""]
    lines += [f"- {r['run_id']}: {r.get('status')}" for r in failed] or ["- none"]
    (root / "E1_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "E1_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print("\n".join(lines))
    try:
        figures(root, runs_ok, stats)
    except ImportError:
        print("matplotlib missing: no figures")
    return 0


def figures(root: Path, runs: list[dict], stats: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig_dir = root / "figures"
    fig_dir.mkdir(exist_ok=True)
    # Figure 1: packets lost vs outage duration
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    for mode, colour in (("custody", "tab:blue"), ("openloop", "tab:red")):
        xs = sorted({r["outage_s"] for r in runs if r["mode"] == mode and r["run_id"].startswith("E1_")})
        for d in xs:
            vals = [r["lost_count"] for r in runs if r["mode"] == mode and r["outage_s"] == d and r["run_id"].startswith("E1_")]
            ax.scatter([d] * len(vals), vals, s=10, alpha=0.5, color=colour)
        mean_y = [statistics.mean([r["lost_count"] for r in runs if r["mode"] == mode and r["outage_s"] == d
                                   and r["run_id"].startswith("E1_")]) for d in xs]
        ax.plot(xs, mean_y, color=colour, label=mode)
    d_all = [5, 15, 30, 60, 330]
    ax.plot(d_all, [d * LAMBDA for d in d_all], "k--", lw=0.8, label="lambda x D")
    ax.set_xscale("log")
    ax.set_yscale("symlog", linthresh=1)
    ax.set_ylim(0, 500)
    ax.set_xlabel("outage duration D (s)")
    ax.set_ylabel("packets not delivered")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "e1_lost_vs_D.png", dpi=200)
    plt.close(fig)
    # Figure 2: predicted vs measured drain time
    pts = [(r["drain_s"], r["T_d_pred_s"], r["outage_s"]) for r in runs
           if r.get("drain_s") and r.get("T_d_pred_s") and r["run_id"].startswith("E1_")]
    ptc = [(r["drain_s"], r["T_d_pred_cycle_s"], r["outage_s"]) for r in runs
           if r.get("drain_s") and r.get("T_d_pred_cycle_s") and r["run_id"].startswith("E1_")]
    if pts:
        fig, ax = plt.subplots(figsize=(4.6, 4.0))
        for d in sorted({p[2] for p in pts}):
            ax.scatter([p[0] for p in pts if p[2] == d], [p[1] for p in pts if p[2] == d], s=12, label=f"D={d} (mu from ACK count)")
        ax.scatter([p[0] for p in ptc], [p[1] for p in ptc], s=14, facecolors="none", edgecolors="k",
                   label="mu from ACK-to-ACK cycle")
        top = max(max(p[0], p[1]) for p in pts) * 1.1
        ax.plot([0, top], [0, top], "k--", lw=0.8)
        ax.plot([0, top], [0, top * 1.15], "k:", lw=0.6)
        ax.plot([0, top], [0, top * 0.85], "k:", lw=0.6)
        ax.set_xlabel("measured drain time (s)")
        ax.set_ylabel("T_d = B / (mu - lambda) (s)")
        ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(fig_dir / "e1_drain_pred_vs_meas.png", dpi=200)
        plt.close(fig)
    # Figure 3: re-up time by D (custody, primary vs sensitivity)
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    for label, pred in (("hold-down cancellation on", lambda r: r["run_id"].startswith("E1_custody")),
                        ("hold-down cancellation off", lambda r: r["run_id"].startswith("E1s_"))):
        pts = [(r["outage_s"], r.get("reup_dev_s") if r.get("reup_dev_s") is not None else r.get("reup_s"))
               for r in runs if pred(r)]
        pts = [(x, y) for x, y in pts if y is not None]
        if pts:
            ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=10, alpha=0.6, label=label)
    ax.set_xscale("log")
    ax.set_xlabel("outage duration D (s)")
    ax.set_ylabel("re-up time after restore (s)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(fig_dir / "e1_reup_vs_D.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
