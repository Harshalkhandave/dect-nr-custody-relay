#!/usr/bin/env python3
"""
Analyse run folders under data/dryrun/harness_runs and write result.json per run
plus data/dryrun/harness_runs/SUMMARY.md.  Reads raw logs only; never edits them.

  python analyze_run.py                # all run folders
  python analyze_run.py R1_custody_60  # one folder

Metrics: unique PDR = distinct sequence numbers
delivered at the sink / distinct sequence numbers first-sent by the source
(TX type=DATA retx=0). Outage timing uses host time stamps of the command and
of the logged line, so it is only good to the logger latency (tens of ms).
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "data" / "dryrun" / "harness_runs"
LINE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d\d\d)\]\s(.*)$")
ERRORS = re.compile(r"messages dropped|BAD_FRAME|rx submit|tx submit|modem_timeout|rx cancel timed out|"
                    r"rx_error|phy op handle|boot-loop guard|CONNECTION LOST|<err>|<wrn>")


def secs(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def host_secs(text: str) -> float:
    h, m, rest = text.split(":")
    s, ms = rest.split(".")
    return secs(h, m, s, ms)


def load(path: Path) -> list[tuple[float, str]]:
    out = []
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(raw)
        if m:
            out.append((secs(*m.groups()[:4]), m.group(5)))
    return out


def kv(text: str) -> dict:
    return dict(re.findall(r"(\w+)=(\S+)", text))


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))]


def analyse(folder: Path) -> dict:
    man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    ev = json.loads((folder / "events.json").read_text(encoding="utf-8"))
    ids = man["ids"]
    src = load(folder / "source.txt")
    rel = load(folder / "relay.txt")
    snk = load(folder / "sink.txt")
    ev_t = {e["event"]: host_secs(e["host_time"]) for e in ev["commands"]}
    res: dict = {"rx_slice": man.get("rx_slice", 15), "run_id": man["run_id"], "status": man.get("status"), "custody": man["custody"],
                 "count": man["count"], "outage_s": man["outage_s"]}

    # sent / delivered
    sent = []
    retx_data = 0
    for _, t in src:
        if "app: TX:" in t and "type=DATA" in t:
            d = kv(t)
            if d.get("retx") == "0":
                sent.append(int(d["seq"]))
            elif d.get("retx") == "1":
                retx_data += 1
    deliv = [int(kv(t)["seq"]) for _, t in snk
             if "app: DELIVER:" in t and kv(t).get("src") == str(ids["source"])]
    sent_set, deliv_set = set(sent), set(deliv)
    res["sent_unique"] = len(sent_set)
    res["delivered_unique"] = len(deliv_set & sent_set)
    res["delivered_lines"] = len(deliv)
    res["duplicate_deliveries"] = len(deliv) - len(set(deliv))
    res["unique_pdr"] = round(len(deliv_set & sent_set) / len(sent_set), 4) if sent_set else None
    res["lost_seq"] = sorted(sent_set - deliv_set)[:40]
    res["lost_count"] = len(sent_set - deliv_set)
    res["source_retx_data"] = retx_data
    gaps = [kv(t) for _, t in snk if "app: RX_GAP:" in t]
    res["sink_rx_gap_events"] = len(gaps)

    # per-hop first-attempt loss (hop 1: source -> relay, hop 2: relay -> sink)
    relay_rx = {int(kv(t)["seq"]) for _, t in rel
                if "app: RX:" in t and "type=DATA" in t and kv(t).get("src") == str(ids["source"])}
    relay_first = [int(kv(t)["seq"]) for _, t in rel
                   if "app: TX:" in t and "type=DATA" in t and kv(t).get("retx") == "0"]
    relay_retx = sum(1 for _, t in rel if "app: TX:" in t and "type=DATA" in t and kv(t).get("retx") == "1")
    if man["custody"]:
        res["hop1_first_attempt_fail"] = round(retx_data / len(sent), 3) if sent else None
        res["hop2_first_attempt_fail"] = round(relay_retx / len(relay_first), 3) if relay_first else None
    elif man["outage_s"] is None and sent:
        res["hop1_loss"] = round(len(sent_set - relay_rx) / len(sent_set), 3)
        got = [x for x in sent_set if x in relay_rx]
        res["hop2_loss"] = round(len([x for x in got if x not in deliv_set]) / len(got), 3) if got else None

    # overflow indicators
    res["relay_queue_full_nacks"] = sum(1 for _, t in rel if "app: NACK_TX:" in t and "QUEUE_FULL" in t)
    sd = [int(kv(t)["depth"]) for _, t in src if "app: STORED: node=%s" % ids["source"] in t]
    res["source_peak_depth"] = max(sd) if sd else None
    res["drop_expired_or_overflow_lines"] = sum(1 for L in (src, rel, snk) for _, t in L
                                                if "DROP_EXPIRED" in t or "CUSTODY_BROKEN" in t)

    # errors
    errs = {}
    for name, lines in (("source", src), ("relay", rel), ("sink", snk)):
        hits = [t for _, t in lines if ERRORS.search(t) and not t.startswith(">>>")]
        if hits:
            errs[name] = hits[:5]
    res["error_lines"] = errs

    # RTT (custody): ACK_RX lines for DATA
    rtts = {"source": [], "relay": []}
    probe_rtts = []
    for name, lines in (("source", src), ("relay", rel)):
        for _, t in lines:
            if "app: ACK_RX:" in t:
                d = kv(t)
                try:
                    r = float(d["rtt_ms"])
                except (KeyError, ValueError):
                    continue
                if d.get("status") in ("ACCEPTED", "DUPLICATE"):
                    rtts[name].append(r)
                elif d.get("status") == "PROBE_REPLY":
                    probe_rtts.append(r)
    for name, v in rtts.items():
        res[f"rtt_ms_{name}"] = ({"n": len(v), "median": statistics.median(v), "p95": pct(v, 0.95),
                                  "max": max(v)} if v else None)
    res["probe_rtt_ms"] = ({"n": len(probe_rtts), "median": statistics.median(probe_rtts)}
                           if probe_rtts else None)
    res["retry_lines"] = {n: sum(1 for _, t in L if "app: RETRY:" in t)
                          for n, L in (("source", src), ("relay", rel))}
    res["ack_lines_in_open_loop"] = sum(1 for L in (src, rel, snk) for _, t in L
                                        if "app: ACK_TX:" in t or "app: ACK_RX:" in t
                                        or "type=PROBE" in t or "app: LINK_STATE:" in t) \
        if not man["custody"] else None

    # link events
    def links(lines):
        out = []
        for ht, t in lines:
            if "app: LINK_STATE:" in t:
                d = kv(t)
                out.append({"host": ht, "next": int(d["next"]), "old": d["old"], "new": d["new"],
                            "reason": d.get("reason"), "time_us": int(d["time_us"])})
        return out
    rl, sl = links(rel), links(src)
    res["relay_link_events"] = [{k: v for k, v in e.items() if k != "host"} for e in rl][:40]
    res["source_link_events"] = [{k: v for k, v in e.items() if k != "host"} for e in sl][:20]

    # outage timing
    if man["outage_s"] is not None and "outage_start" in ev_t:
        o0, o1 = ev_t["outage_start"], ev_t.get("outage_end")
        sink_id = ids["sink"]
        down = [e for e in rl if e["next"] == sink_id and e["new"] == "DOWN" and e["host"] >= o0]
        up = [e for e in rl if e["next"] == sink_id and e["new"] == "UP" and o1 and e["host"] >= o1]
        res["outage_start_host"] = o0
        if man["custody"]:
            res["detection_s"] = round(down[0]["host"] - o0, 3) if down else None
            res["reup_s"] = round(up[0]["host"] - o1, 3) if up else None
            # backlog and drain
            depth = []
            for ht, t in rel:
                if "app: STORED:" in t:
                    d = kv(t)
                    depth.append((ht, int(d["depth"])))
            res["relay_peak_depth"] = max((d for _, d in depth), default=None)
            if up:
                t_up = up[0]["host"]
                before = [d for ht, d in depth if ht <= t_up]
                B = before[-1] if before else None
                res["backlog_B_at_link_up"] = B
                # relay DATA forwards after link up (device time_us, retx=0)
                fwd = []
                for _, t in rel:
                    if "app: TX:" in t and "type=DATA" in t and kv(t).get("retx") == "0":
                        d = kv(t)
                        fwd.append((int(d["time_us"]), int(d["seq"])))
                up_us = up[0]["time_us"]
                after = [x for x in fwd if x[0] >= up_us]
                if B and len(after) >= B:
                    span = (after[B - 1][0] - up_us) / 1e6
                    res["drain_span_s_first_B_frames"] = round(span, 2)
                    res["mu_est_pkt_s"] = round(B / span, 2) if span > 0 else None
                    lam = 1.0
                    if res["mu_est_pkt_s"] and res["mu_est_pkt_s"] > lam:
                        res["T_d_predicted_s"] = round(B / (res["mu_est_pkt_s"] - lam), 2)
        else:
            exp_loss = man["outage_s"] * 1.0
            res["open_loop_expected_loss"] = exp_loss
            res["open_loop_loss_vs_expected"] = round(res["lost_count"] / exp_loss, 2) if exp_loss else None

    # device-clock detection and re-up (STOP and START carry time_us), offset by DATA pairs
    if man["outage_s"] is not None and man["custody"]:
        tx_r = {}
        retr = set()
        for _, t in rel:
            if "app: TX:" in t and "type=DATA" in t:
                d = kv(t)
                if d.get("retx") == "0":
                    tx_r[int(d["seq"])] = int(d["time_us"])
                else:
                    retr.add(int(d["seq"]))
        rx_s = {int(kv(t)["seq"]): int(kv(t)["time_us"]) for _, t in snk if "app: DELIVER:" in t}
        pairs = [(tx_r[q], rx_s[q]) for q in tx_r if q in rx_s and q not in retr]
        sink_stop = [kv(t) for _, t in snk if "app: STOP:" in t and "reason=user" in t and "time_us=" in t]
        sink_start = [kv(t) for _, t in snk if "app: START:" in t and "time_us=" in t]
        if len(pairs) >= 10 and sink_stop and len(sink_start) >= 2:
            ts = [t / 1e6 for t, _ in pairs]
            dl = [(r - t) / 1e3 for t, r in pairs]  # ms: sink clock minus relay clock plus latency
            n_ = len(ts)
            mx, my = sum(ts) / n_, sum(dl) / n_
            b_ = sum((x - mx) * (y - my) for x, y in zip(ts, dl)) / sum((x - mx) ** 2 for x in ts)
            resid = sorted(y - (my + b_ * (x - mx)) for x, y in zip(ts, dl))
            low = resid[max(0, int(0.05 * len(resid)))]  # fastest frames approximate zero latency

            def to_relay_us(sink_us: int) -> float:
                # solve t_relay = t_sink - offset(t_relay), offset linear in t_relay (ms -> us)
                t = sink_us / 1e6
                for _ in range(3):
                    off_ms = my + b_ * (t - mx) + low
                    t = sink_us / 1e6 - off_ms / 1e3
                return t * 1e6
            t_stop = to_relay_us(int(sink_stop[0]["time_us"]))
            t_start = to_relay_us(int(sink_start[1]["time_us"]))
            dn = [e for e in rl if e["next"] == ids["sink"] and e["new"] == "DOWN" and e["time_us"] >= t_stop - 2e6]
            upl = [e for e in rl if e["next"] == ids["sink"] and e["new"] == "UP" and e["time_us"] >= t_start - 2e6]
            res["clock_offset_fit"] = {"pairs": n_, "drift_us_per_s": round(b_ * 1000, 1),
                                       "resid_sd_ms": round(statistics.pstdev(resid), 1)}
            res["detection_dev_s"] = round((dn[0]["time_us"] - t_stop) / 1e6, 3) if dn else None
            res["reup_dev_s"] = round((upl[0]["time_us"] - t_start) / 1e6, 3) if upl else None

    # counters printed by `exp status` (shell, not the log) against counts from the log
    cnt = ev.get("counters_after") or {}
    def num(lines, key):
        for ln in lines:
            m = re.search(rf"{key}=(\d+)", ln)
            if m:
                return int(m.group(1))
        return None
    chk = {}
    gen = num(cnt.get("source", []), "generated")
    chk["source_generated_vs_log"] = None if gen is None else (gen, len(sent_set))
    if man["outage_s"] is None:
        dl_c = num(cnt.get("sink", []), "delivered")
        chk["sink_delivered_vs_log"] = None if dl_c is None else (dl_c, len(deliv))
    ret = num(cnt.get("source", []), "retries")
    chk["source_retries_vs_log"] = None if ret is None else (ret, res["retry_lines"]["source"])
    res["counter_crosscheck"] = chk

    # final lines
    res["source_stop"] = next((t for _, t in reversed(src) if "app: STOP:" in t), None)
    sm = [t for _, t in src if "app: SUMMARY:" in t]
    res["source_summary"] = sm[-1] if sm else None
    rs = ev.get("relay_status_after") or []
    res["relay_status_after"] = rs

    # verdict
    checks = {}
    checks["no_error_lines"] = not errs
    checks["source_finished"] = bool(res["source_stop"] and "count_reached" in res["source_stop"])
    if man["custody"]:
        checks["all_delivered"] = res["lost_count"] == 0 and res["sent_unique"] == man["count"]
        if man["outage_s"] is not None:
            checks["link_down_detected"] = res.get("detection_s") is not None
            checks["link_reup"] = res.get("reup_s") is not None
        r = res.get("rtt_ms_source")
        checks["rtt_below_ack_window"] = bool(r and r["median"] < 100)
    else:
        checks["no_custody_traffic"] = res["ack_lines_in_open_loop"] == 0
        # Open-loop delivery is reported, not asserted: idle receive slices lose frames
        # that straddle a slice boundary even on a strong link (see SUMMARY.md notes).
        first = min(sent_set) if sent_set else 0
        res["open_loop_pdr"] = res["unique_pdr"]
        if man["outage_s"] is not None:
            lo, hi = first + 30, first + 30 + man["outage_s"]
            lost = sorted(sent_set - deliv_set)
            in_out = [x for x in lost if lo <= x < hi]
            out_out = [x for x in lost if not (lo <= x < hi)]
            n_out = len([x for x in sent_set if not (lo <= x < hi)])
            res["lost_in_outage_window"] = len(in_out)
            res["lost_outside_outage_window"] = len(out_out)
            res["baseline_loss_rate_outside_outage"] = round(len(out_out) / n_out, 3) if n_out else None
            res["info_E1_criterion_raw_lost_over_lambdaD"] = res.get("open_loop_loss_vs_expected")
            res["info_E1_criterion_outage_only_lost_over_lambdaD"] = round(len(in_out) / man["outage_s"], 2)
    for k, v in (res.get("counter_crosscheck") or {}).items():
        if v is not None:
            checks[k] = v[0] == v[1]
    res["checks"] = checks
    res["pass"] = all(checks.values())
    return res


def main() -> int:
    global ROOT
    names = sys.argv[1:]
    if names and names[0] == "--root":
        ROOT = Path(names[1])
        names = names[2:]
    folders = [ROOT / n for n in names] if names else sorted(
        p for p in ROOT.iterdir() if p.is_dir() and (p / "manifest.json").exists())
    results = []
    for f in folders:
        if not (f / "manifest.json").exists():
            print(f"skip {f.name}: no manifest")
            continue
        r = analyse(f)
        (f / "result.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
        results.append(r)
        print(f"{r['run_id']}: pass={r['pass']} pdr={r['unique_pdr']} checks={r['checks']}")

    lines = ["# Dry-run summary", "",
             f"Generated {datetime.now().isoformat(timespec='seconds')} by `tools/harness/analyze_run.py` from the raw logs in this folder.",
             "Dry-run data, not results of the outage sweep. Runs with `reboot_between_runs` true were started after `exp reboot` on all three boards; the first set of dry runs ran on one boot without reboots.", "",
             "| run | mode | slice ms | N | outage s | sent | delivered | lost | unique PDR | hop1 / hop2 loss or first-attempt fail | RTT src median/max ms | detect s | re-up s | B | mu est | pass |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|:--:|"]
    for r in results:
        rt = r.get("rtt_ms_source")
        rtxt = f"{rt['median']:.0f}/{rt['max']:.0f}" if rt else "-"
        h1 = r.get("hop1_first_attempt_fail", r.get("hop1_loss"))
        h2 = r.get("hop2_first_attempt_fail", r.get("hop2_loss"))
        htxt = f"{h1:.2f} / {h2:.2f}" if h1 is not None and h2 is not None else "-"
        lines.append("| {run} | {mode} | {sl} | {n} | {o} | {s} | {d} | {l} | {p} | {h} | {rt} | {de} | {ru} | {b} | {mu} | {ok} |".format(
            run=r["run_id"], mode="custody" if r["custody"] else "open-loop", n=r["count"],
            sl=r.get("rx_slice", 15), h=htxt,
            o=r["outage_s"] if r["outage_s"] is not None else "-", s=r["sent_unique"],
            d=r["delivered_unique"], l=r["lost_count"],
            p=f"{r['unique_pdr']:.3f}" if r["unique_pdr"] is not None else "-", rt=rtxt,
            de=r.get("detection_s", "-"), ru=r.get("reup_s", "-"),
            b=r.get("backlog_B_at_link_up", "-"), mu=r.get("mu_est_pkt_s", "-"),
            ok="yes" if r["pass"] else "NO"))
    lines += ["", "## Check detail", ""]
    for r in results:
        lines.append(f"- **{r['run_id']}**: " + ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in r["checks"].items()))
        if r["error_lines"]:
            lines.append(f"  - error lines: {json.dumps(r['error_lines'])[:300]}")
        if r["lost_count"]:
            lines.append(f"  - lost seq (first 40): {r['lost_seq']}")
    (ROOT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {ROOT / 'SUMMARY.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
