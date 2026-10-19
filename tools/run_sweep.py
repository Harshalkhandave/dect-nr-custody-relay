#!/usr/bin/env python3
"""
Run a randomised, replicate-blocked sweep of conditions with the run harness and save each run in
its own folder. Used for the outage sweep (E1).

Design:
  * every replicate contains all conditions once, in a seeded random order; if the sweep is
    stopped early, every condition has the same number of runs (+-1);
  * every run starts with `exp reboot` on all three boards and a full settings read-back;
  * the schedule (with the seed) is written first and never changed; a rerun of this command
    skips runs whose folder already has a manifest.json (resume after an interruption);
  * a run that raised an error is kept and marked in its manifest, not deleted.

Usage:
  python tools/run_sweep.py --sweep e1 --out data/E1_outage_sweep --replicates 10 --seed 20261005 \
      --sink COM7 --relay COM8 --source COM9
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "harness"))
import harness as h  # noqa: E402

GAPS_E1 = {"relay": 5, "source": 35}  # inter-transmission gaps (ms) used in the sweep


def e1_conditions() -> dict:
    conds = {}
    for d in (5, 15, 30, 60, 330):
        n = 30 + d + 90
        tail = 30
        for mode in ("custody", "openloop"):
            conds[f"E1_{mode}_D{d:03d}"] = dict(
                custody=(mode == "custody"), count=n, outage_s=d, tail_s=tail, gaps=GAPS_E1,
                notes=f"E1 {mode} D={d} s N={n}")
    # sensitivity block: the old hold-down staircase (hold_cancel 0), custody, D = 60 s
    conds["E1s_custody_D060_holdcancel0"] = dict(
        custody=True, count=180, outage_s=60, tail_s=30, gaps=GAPS_E1,
        extra={"all": {"hold_cancel": 0}}, notes="E1 sensitivity: hold_cancel 0 (old staircase), D=60 s")
    return conds


def e2_conditions(settings: dict, with_soak: bool = False) -> dict:
    conds = {}
    for tag, (cancel, rxm) in settings.items():
        ex = {"all": {"cancel_ack": cancel, "rx_mode": rxm}}
        conds[f"E2{tag}_drain"] = dict(
            custody=True, count=300, outage_s=180, tail_s=30, gaps=GAPS_E1, extra=ex,
            notes=f"E2 {tag}: cancel_ack {cancel}, rx_mode {rxm}, 180 s outage then drain")
        conds[f"E2{tag}_steady"] = dict(
            custody=True, count=300, outage_s=None, tail_s=20, gaps=GAPS_E1, extra=ex,
            notes=f"E2 {tag}: cancel_ack {cancel}, rx_mode {rxm}, steady 300 frames")
        if with_soak:
            conds[f"E2{tag}_soak"] = dict(
                custody=True, count=1800, outage_s=None, tail_s=20, gaps=GAPS_E1, extra=ex,
                notes=f"E2 {tag}: cancel_ack {cancel}, rx_mode {rxm}, 30 min soak")
    return conds


def switch_conditions() -> dict:
    """Two-board-plus checks that each runtime switch changes behaviour on hardware (60 frames, strong link)."""
    base = dict(custody=True, count=60, outage_s=None, tail_s=15, gaps=GAPS_E1)
    return {
        "SW_cancel_off": dict(base, extra={"all": {"cancel_ack": "off"}}, notes="switch: cancel_ack off (ACK window runs 200 ms / 400 ms)"),
        "SW_rx_slice": dict(base, extra={"all": {"rx_mode": "slice"}}, notes="switch: rx_mode slice"),
        "SW_liveness_hello": dict(base, extra={"all": {"liveness": "hello"}}, notes="switch: liveness hello only"),
        "SW_ctrl04": dict(base, extra={"all": {"ctrl_subslots": 4}}, notes="switch: ctrl_subslots 4"),
        "SW_ctrl16": dict(base, extra={"all": {"ctrl_subslots": 16}}, notes="switch: ctrl_subslots 16"),
        "SW_default": dict(base, notes="switch: defaults, reference"),
    }


E2_MAIN = {"A": ("off", "slice"), "B": ("on", "event")}
E2_MIX = {"C": ("off", "event"), "D": ("on", "slice")}

SWEEPS = {"e1": e1_conditions, "switch": switch_conditions,
          "e2": lambda: e2_conditions(E2_MAIN), "e2mix": lambda: e2_conditions(E2_MIX),
          "e2soak": lambda: {k: v for k, v in e2_conditions(E2_MAIN, True).items() if k.endswith("soak")}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", required=True, choices=sorted(SWEEPS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--replicates", type=int, default=10)
    ap.add_argument("--first", type=int, default=1, help="first replicate number")
    ap.add_argument("--seed", type=int, default=20261005)
    port_help = "serial port or pyserial URL, for example COM7 or socket://HOST:7777"
    ap.add_argument("--sink", required=True, help="sink: " + port_help)
    ap.add_argument("--relay", required=True, help="relay: " + port_help)
    ap.add_argument("--source", required=True, help="source: " + port_help)
    ap.add_argument("--only", default=None, help="comma list of condition names to run")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    h.OUT_ROOT = out
    conds = SWEEPS[args.sweep]()
    if args.only:
        keep = set(args.only.split(","))
        conds = {k: v for k, v in conds.items() if k in keep}
    sched_path = out / "schedule.json"
    if sched_path.exists():
        schedule = json.loads(sched_path.read_text(encoding="utf-8"))["runs"]
    else:
        rng = random.Random(args.seed)
        schedule = []
        for rep in range(args.first, args.first + args.replicates):
            names = sorted(conds)
            rng.shuffle(names)
            schedule += [{"run_id": f"{c}_r{rep:02d}", "condition": c, "replicate": rep} for c in names]
        sched_path.write_text(json.dumps({"seed": args.seed, "runs": schedule,
                                          "conditions": conds}, indent=2), encoding="utf-8")
        print(f"schedule written: {len(schedule)} runs, seed {args.seed}", flush=True)

    urls = {"sink": args.sink, "relay": args.relay, "source": args.source}
    boards: dict = {}

    def connect(first: bool = False) -> None:
        """(Re)open the three serial connections; the TCP bridge has dropped a connection before."""
        for b in boards.values():
            b.close()
        boards.clear()
        last = None
        for attempt in range(1, 11):
            try:
                for n, u in urls.items():
                    boards[n] = h.Board(n, u)
                time.sleep(1.0)
                for b in boards.values():
                    b.send("")
                time.sleep(0.5)
                h.read_ids(boards)
                if first:
                    for b in boards.values():
                        b.cmd("exp factory", expect=r"profile erased")
                return
            except Exception as err:  # noqa: BLE001
                last = err
                print(f"    connect attempt {attempt} failed: {err}", flush=True)
                for b in boards.values():
                    b.close()
                boards.clear()
                time.sleep(30)
        raise SystemExit(f"cannot reconnect: {last}")

    INFRA = ("write failed", "read failed", "CONNECTION LOST", "socket", "could not open", "no idle prompt",
             "echo not seen", "failed after")
    try:
        connect(first=True)
        t_start = time.monotonic()
        done = 0
        for item in schedule:
            rid = item["run_id"]
            if any((out / f"{rid}{sfx}" / "manifest.json").exists() and
                   json.loads((out / f"{rid}{sfx}" / "manifest.json").read_text(encoding="utf-8")).get("status") == "ok"
                   for sfx in ["", "_retry1", "_retry2", "_retry3"] if (out / f"{rid}{sfx}").exists()):
                continue
            cond = dict(conds.get(item["condition"]) or json.loads(
                sched_path.read_text(encoding="utf-8"))["conditions"][item["condition"]])
            cond["notes"] = f"{cond.get('notes', '')}; replicate {item['replicate']}; seed {args.seed}"
            for attempt in range(4):
                run_id = rid if attempt == 0 else f"{rid}_retry{attempt}"
                if (out / run_id / "manifest.json").exists():
                    continue  # an earlier attempt exists (kept, marked failed): use the next id
                if any(not b.alive for b in boards.values()):
                    print("    a connection is down: reconnecting", flush=True)
                    connect()
                print(f"--- {run_id} start {h.host_ts()}", flush=True)
                try:
                    res = h.run_scenario(boards, run_id, **cond)
                except Exception as err:  # noqa: BLE001  setup failed before the run started
                    res = {"run_id": run_id, "status": f"setup_error: {err}"}
                print(f"--- {run_id} {res['status']} {h.host_ts()}", flush=True)
                if res["status"] == "ok" or not any(w in str(res["status"]) for w in INFRA) and                         not str(res["status"]).startswith(("setup_error", "error")):
                    break  # ok, or a real run outcome such as timeout
                print("    infrastructure failure: reconnect and rerun under a new id", flush=True)
                time.sleep(20)
                connect()
            done += 1
            print(f"    elapsed {(time.monotonic() - t_start) / 60:.1f} min, {done} runs this session", flush=True)
    finally:
        for b in boards.values():
            b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
