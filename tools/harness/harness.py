#!/usr/bin/env python3
"""
Run harness: drives three boards (sink, relay, source) over their shell UARTs,
runs a scenario and saves raw logs plus a manifest per run.

Output: data/dryrun/harness_runs/<run_id>/{source,relay,sink}.txt, config_*.txt,
events.json, manifest.json.  Raw log files are never edited. Analysis is done
afterwards by analyze_run.py. tools/run_sweep.py uses this module for the sweep.

Ports are pyserial URLs: COM7, socket://HOST:7777, ...

Example:
  python tools/harness/harness.py \
      --sink COM7 --relay socket://HOST:7777 --source socket://HOST:7778 \
      --runs R1_custody_60

Boards cannot be rebooted from the shell (no `kernel reboot`), so runs follow
each other on the same boot unless the sweep driver reboots them. That carries
state between runs (links, sequence numbers, dedup high-water mark); this is
recorded in each manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import serial
except ImportError:  # pragma: no cover
    raise SystemExit("Missing pyserial: python -m pip install -r tools/logger/requirements.txt")

REPO = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO / "data" / "dryrun" / "harness_runs"
ANSI = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
ERR_RX = re.compile(r"wrong parameter count|stop the run|unknown key|source needs dest|does not fit|"
                    r"not an integer|role is source|value is on|already running|start failed|"
                    r"usage: exp (sett|start|role)|^rejected$|dst and next|dst is not")


def host_ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def clean(s: str) -> str:
    return ANSI.sub("", s).replace("\r", "").strip()


class Board:
    """One shell UART with a reader thread. Lines are timestamped on the host."""

    def __init__(self, name: str, url: str):
        self.name = name
        self.url = url
        self.ser = serial.serial_for_url(url, baudrate=115200, timeout=0.2)
        self.lines: list[tuple[float, str]] = []  # (monotonic, text) for wait_for
        self.lock = threading.Lock()
        self.logf = None
        self.stop = threading.Event()
        self.alive = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()
        self.node_id: int | None = None
        self.boot_lines: list[str] = []  # BOOT_INFO / BOOT_MODEM lines of the last reboot

    def _reader(self) -> None:
        buf = bytearray()
        while not self.stop.is_set():
            try:
                chunk = self.ser.read(256)
            except Exception as err:  # connection lost
                self.alive = False
                self._add(f"### CONNECTION LOST: {err}")
                return
            if not chunk:
                continue
            buf.extend(chunk)
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                raw = bytes(buf[: nl + 1])
                del buf[: nl + 1]
                line = clean(raw.decode("utf-8", errors="replace"))
                if line:
                    self._add(line)

    def _add(self, line: str) -> None:
        text = f"[{host_ts()}] {line}"
        with self.lock:
            self.lines.append((time.monotonic(), line))
            if self.logf is not None:
                self.logf.write(text + "\n")
                self.logf.flush()

    def open_log(self, path: Path, header: str) -> None:
        with self.lock:
            self.logf = path.open("w", encoding="utf-8", newline="")
            self.logf.write(f"===== {header} port={self.url} =====\n")

    def close_log(self) -> None:
        with self.lock:
            if self.logf is not None:
                self.logf.close()
                self.logf = None

    def mark(self) -> int:
        with self.lock:
            return len(self.lines)

    def since(self, mark: int) -> list[str]:
        with self.lock:
            return [t for _, t in self.lines[mark:]]

    def send(self, cmd: str) -> None:
        self._add(f">>> {cmd}")
        self.type_line(cmd)

    def wait_for(self, pattern: str, mark: int, timeout: float) -> str | None:
        rx = re.compile(pattern)
        end = time.monotonic() + timeout
        seen = mark
        while time.monotonic() < end:
            with self.lock:
                batch = self.lines[seen:]
                seen = len(self.lines)
            for _, text in batch:
                if rx.search(text):
                    return text
            if not self.alive:
                return None
            time.sleep(0.05)
        return None

    def type_line(self, text: str) -> None:
        """Clear any partial input (Ctrl-U), then type slowly: the serial bridge and the
        shell have been seen to drop characters when a line arrives in one burst."""
        self.ser.write(bytes([0x15]))
        time.sleep(0.05)
        for ch in text:
            self.ser.write(ch.encode())
            time.sleep(0.004)
        self.ser.write(bytes([0x0D]))

    def cmd(self, text: str, expect: str | None = None, timeout: float = 4.0,
            attempts: int = 3) -> list[str]:
        """Send a shell command; the shell must echo it back unchanged. Retry on a lost or
        garbled line; raise if the reply does not match or the shell reports an error."""
        last = ""
        for attempt in range(1, attempts + 1):
            m = self.mark()
            self._add(f">>> {text}" + (f"   (retry {attempt})" if attempt > 1 else ""))
            if attempt > 1:
                # flush any half-typed line left by a dropped character, then start clean
                self.ser.write(bytes([0x0D]))
                time.sleep(0.4)
                m = self.mark()
            self.type_line(text)
            if self.wait_for(r"^(?!>>>)(?:.*[\s$])?" + re.escape(text) + r"\s*$", m, 1.8) is None:
                last = f"echo not seen: {self.since(m)[-3:]}"
                time.sleep(0.4)
                continue
            if expect is not None:
                if self.wait_for(expect, m, timeout) is None:
                    raise RuntimeError(f"{self.name}: no reply matching /{expect}/ to '{text}': "
                                       f"{self.since(m)[-4:]}")
            else:
                time.sleep(0.35)
            time.sleep(0.1)
            reply = self.since(m)
            for line in reply:
                low = line.lower()
                if "<inf>" in line or line.startswith(">>>"):
                    continue  # protocol log lines are not shell replies
                if ERR_RX.search(low):
                    raise RuntimeError(f"{self.name}: '{text}' -> {line}")
            return reply
        raise RuntimeError(f"{self.name}: '{text}' failed after {attempts} attempts ({last})")

    def reboot(self, timeout: float = 25.0) -> None:
        """exp reboot, then wait for the new boot to reach the idle prompt."""
        m = self.mark()
        self.cmd("exp reboot", expect=r"rebooting", timeout=5)
        if self.wait_for(r"idle . exp start", m, timeout) is None:
            raise RuntimeError(f"{self.name}: no idle prompt after exp reboot")
        time.sleep(0.5)
        self.boot_lines = [ln for ln in self.since(m) if "BOOT_INFO:" in ln or "BOOT_MODEM:" in ln]

    def close(self) -> None:
        self.stop.set()
        try:
            self.ser.close()
        except Exception:
            pass


def parse_boot_info(boards: dict) -> dict:
    """Identity of what each board is running, read from its own boot log (BOOT_INFO and BOOT_MODEM)."""
    out = {}
    for name, b in boards.items():
        d: dict = {}
        for ln in b.boot_lines:
            tag = "boot_info" if "BOOT_INFO:" in ln else "boot_modem"
            body = ln.split("BOOT_INFO:" if tag == "boot_info" else "BOOT_MODEM:", 1)[1].strip()
            if tag == "boot_modem":  # hw= contains spaces ("nRF9151 LACA A1A")
                mm = re.match(r"fw=(.*?) hw=(.*?) uuid=(\S+) temp_c=(\S+) vbat_mv=(\S+)", body)
                d[tag] = dict(zip(("fw", "hw", "uuid", "temp_c", "vbat_mv"), mm.groups())) if mm else {}
            else:
                d[tag] = dict(re.findall(r"(\w+)=(\S+)", body))
            d[tag + "_line"] = body
        out[name] = d or None  # None: the image does not print the boot lines or they were not captured
    return out


def host_info() -> dict:
    import platform
    try:
        pyserial = serial.__version__
    except Exception:
        pyserial = "unknown"
    return {"os": platform.platform(), "python": platform.python_version(), "pyserial": pyserial,
            "harness_git": git_info()["commit"]}


def setup_info() -> dict | None:
    """Physical set-up (layout, distances, antennas, board labels): data/SETUP.json, written by hand (template:
    data/SETUP_TEMPLATE.json). None if the file does not exist."""
    f = REPO / "data" / "SETUP.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        return {"error": f"SETUP.json unreadable: {err}"}


def identity_warnings(info: dict, setup: dict | None) -> list[str]:
    w = []
    revs = {n: (d or {}).get("boot_info", {}).get("fw") for n, d in info.items()}
    mods = {n: (d or {}).get("boot_modem", {}).get("fw") for n, d in info.items()}
    if any(v is None for v in revs.values()):
        w.append("a board did not print BOOT_INFO (image without the boot lines?): " + str([n for n, v in revs.items() if v is None]))
    if len({v for v in revs.values() if v}) > 1:
        w.append(f"boards run different firmware revisions: {revs}")
    if any(v and v.endswith("-dirty") for v in revs.values()):
        w.append(f"a firmware revision is dirty (uncommitted changes): {revs}")
    if len({v for v in mods.values() if v}) > 1:
        w.append(f"boards report different modem firmware: {mods}")
    if setup is None:
        w.append("data/SETUP.json is missing (layout, distances, antennas): see data/SETUP_TEMPLATE.json")
    return w


def git_info() -> dict:
    def run(*a: str) -> str:
        try:
            return subprocess.check_output(["git", *a], cwd=REPO, text=True).strip()
        except Exception:
            return "unknown"
    return {"commit": run("rev-parse", "HEAD"), "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": run("status", "--porcelain", "firmware")}


def read_ids(boards: dict[str, Board]) -> None:
    for b in boards.values():
        out = b.cmd("exp status", expect=r"node=\d+ role=", timeout=5)
        for line in out:
            m = re.search(r"node=(\d+) role=(\w+) running=(\d)", line)
            if m:
                b.node_id = int(m.group(1))
                if m.group(3) == "1":
                    b.cmd("exp stop", expect=r"stopped|not running")
        if b.node_id is None:
            raise RuntimeError(f"{b.name}: could not read node id")


def configure(boards: dict[str, Board], custody: bool, source_ack_ms: int = 400,
              relay_ack_ms: int = 200, power: int = 10, interval_ms: int = 1000,
              rx_slice: int = 15, gaps: dict | None = None,
              source_power: int | None = None, payload: int = 16,
              extra: dict | None = None) -> dict:
    sink, relay, src = boards["sink"], boards["relay"], boards["source"]
    cust = "on" if custody else "off"
    for b in (sink, relay, src):
        b.cmd("exp stop")  # no-op if stopped
    sink.cmd("exp role sink", expect=r"role=sink")
    relay.cmd("exp role relay", expect=r"role=relay")
    src.cmd("exp role source", expect=r"role=source")
    for b in (sink, relay):
        b.cmd("exp sett hello 2000", expect=r"hello=2000")
        b.cmd("exp sett hello_tx on", expect=r"hello_tx=on")
        b.cmd("exp sett direct on", expect=r"direct=on")
    relay.cmd("exp sett assume_up off", expect=r"assume_up=off")
    relay.cmd(f"exp sett ack_timeout {relay_ack_ms}", expect=rf"ack_timeout={relay_ack_ms}")
    src.cmd("exp sett direct off", expect=r"direct=off")
    src.cmd(f"exp sett dest {sink.node_id}", expect=rf"dest={sink.node_id}")
    # Route entries are <destination> <next hop>: the sink is reached through the relay.
    try:
        src.cmd(f"exp route del {relay.node_id}")
    except RuntimeError:
        pass
    src.cmd(f"exp route set {sink.node_id} {relay.node_id}",
            expect=rf"route dst={sink.node_id} next={relay.node_id}")
    src.cmd(f"exp sett size {payload}", expect=rf"size={payload}")
    src.cmd(f"exp sett interval {interval_ms}", expect=rf"interval={interval_ms}")
    src.cmd("exp sett count 0", expect=r"count=0")
    src.cmd("exp sett assume_up off", expect=r"assume_up=off")
    src.cmd(f"exp sett ack_timeout {source_ack_ms}", expect=rf"ack_timeout={source_ack_ms}")
    src.cmd("exp sett policy reject", expect=r"policy=reject")
    for b in (sink, relay, src):
        b.cmd(f"exp sett custody {cust}", expect=rf"custody={cust}")
        b.cmd(f"exp sett power {power}", expect=rf"power={power}")
        b.cmd("exp sett mcs 0", expect=r"mcs=0")
        b.cmd(f"exp sett rx_slice {rx_slice}", expect=rf"rx_slice={rx_slice}")
    for name, g in (gaps or {}).items():
        boards[name].cmd(f"exp sett gap {g}", expect=rf"gap={g}")
    if source_power is not None:
        src.cmd(f"exp sett power {source_power}", expect=rf"power={source_power}")
    # extra runtime settings: {board name or 'all': {key: value}}
    for name, kvs in (extra or {}).items():
        for b2 in (boards.values() if name == "all" else [boards[name]]):
            for k, v in kvs.items():
                b2.cmd(f"exp sett {k} {v}", expect=rf"{k}={re.escape(str(v))}")
    dumps = {}
    for name, b in boards.items():
        m = b.mark()
        b.send("exp sett")
        b.wait_for(r"set with:", m, 5)
        dumps[name] = [ln for ln in b.since(m) if re.match(r"^\w+=", ln)]
        m2 = b.mark()
        b.send("exp route")
        b.wait_for(r"usage: exp route", m2, 4)  # the shell always ends the listing with usage
        route = b.since(m2)
        dumps[name] += [ln for ln in route if ln.startswith("dst=") or ln.startswith("no routes")]
    # read-back checks: every setting this harness chose must match what the board reports
    want_common = {"custody": cust, "power": str(power), "mcs": "0", "dedup": "on",
                   "rx_slice": str(rx_slice)}
    want = {
        "sink": {**want_common, "role": "sink", "hello": "2000", "hello_tx": "on", "direct": "on"},
        "relay": {**want_common, "role": "relay", "hello": "2000", "hello_tx": "on",
                  "direct": "on", "assume_up": "off", "ack_timeout": str(relay_ack_ms)},
        "source": {**want_common, "role": "source", "direct": "off", "dest": str(sink.node_id),
                   "size": str(payload), "interval": str(interval_ms), "count": "0", "assume_up": "off",
                   "ack_timeout": str(source_ack_ms), "policy": "reject"},
    }
    for gname, gval in (gaps or {}).items():
        want[gname]["gap"] = str(gval)
    if source_power is not None:
        want["source"]["power"] = str(source_power)
    for name, kvs in (extra or {}).items():
        for tgt in (list(want) if name == "all" else [name]):
            for k, v in kvs.items():
                want[tgt][k] = str(v)
    problems = []
    for name, d in dumps.items():
        kv = dict(ln.split("=", 1) for ln in d if "=" in ln and not ln.startswith("dst="))
        for k, v in want[name].items():
            if kv.get(k) != v:
                problems.append(f"{name}: {k}={kv.get(k)} (want {v})")
    if not any(ln == f"dst={sink.node_id} next={relay.node_id}" for ln in dumps["source"]):
        problems.append("source route missing or wrong")
    if problems:
        raise RuntimeError("configuration read-back failed: " + "; ".join(problems))
    return dumps


def neighbours_ok(boards: dict[str, Board]) -> dict:
    """Each board should have heard its neighbours' HELLOs (receive path check)."""
    sink, relay = boards["sink"], boards["relay"]
    res = {}
    for b in (sink, relay):
        b.cmd("exp stop")
    for b in (sink, relay):
        b.cmd("exp start", expect=r"started")
    time.sleep(9.0)  # four or more HELLO periods
    for name, b in (("sink", sink), ("relay", relay)):
        m = b.mark()
        b.send("exp neigh")
        time.sleep(1.2)
        res[name] = [ln for ln in b.since(m) if ln.startswith("id=") or "no neighbours" in ln]
    for b in (sink, relay):
        b.cmd("exp stop")
    return res


def start_run(boards: dict[str, Board], run_id: str, meta: dict) -> Path:
    folder = OUT_ROOT / run_id
    folder.mkdir(parents=True, exist_ok=True)
    for name, b in boards.items():
        b.open_log(folder / f"{name}.txt",
                   f"run {run_id} {name} start {datetime.now().isoformat(timespec='seconds')}")
    (folder / "meta_start.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return folder


def end_run(boards: dict[str, Board], folder: Path, events: dict, meta: dict) -> None:
    for b in boards.values():
        b.close_log()
    (folder / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    manifest = dict(meta)
    manifest["git"] = git_info()
    manifest["ids"] = {n: b.node_id for n, b in boards.items()}
    manifest["ports"] = {n: b.url for n, b in boards.items()}
    manifest["end_host_time"] = datetime.now().isoformat(timespec="seconds")
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run_scenario(boards: dict[str, Board], run_id: str, *, custody: bool, count: int,
                 outage_s: int | None, tail_s: int = 20, timeout_extra_s: int = 300,
                 notes: str = "", rx_slice: int = 15, interval_ms: int = 1000,
                 gaps: dict | None = None, reboot: bool = True,
                 source_power: int | None = None, payload: int = 16,
                 extra: dict | None = None, power: int = 10, relay_ack_ms: int = 200,
                 source_ack_ms: int = 400) -> dict:
    sink, relay, src = boards["sink"], boards["relay"], boards["source"]
    meta = {"run_id": run_id, "custody": custody, "count": count, "outage_s": outage_s,
            "interval_ms": interval_ms, "gaps": gaps or {}, "source_power": source_power, "payload": payload, "mcs": 0, "power": power,
            "source_ack_ms": source_ack_ms, "extra": extra or {}, "relay_ack_ms": relay_ack_ms, "rx_slice": rx_slice, "notes": notes, "reboot_between_runs": reboot,
            "host_start": datetime.now().isoformat(timespec="seconds")}
    events: dict = {"commands": []}

    def ev(name: str) -> None:
        events["commands"].append({"event": name, "host_time": host_ts(),
                                   "monotonic": round(time.monotonic(), 3)})

    # Configure first (the config commands go into the previous log buffer: keep them
    # in config_<run>.txt via the read-back dump, then start fresh logs).
    if reboot:
        for b in boards.values():
            b.reboot()
        meta["boot_info"] = parse_boot_info(boards)
        meta["host"] = host_info()
        meta["setup"] = setup_info()
        meta["identity_warnings"] = identity_warnings(meta["boot_info"], meta["setup"])
        for w in meta["identity_warnings"]:
            print(f"    WARNING ({run_id}): {w}", flush=True)
    dumps = configure(boards, custody, rx_slice=rx_slice, interval_ms=interval_ms, gaps=gaps,
                      source_power=source_power, payload=payload, extra=extra, power=power,
                      relay_ack_ms=relay_ack_ms, source_ack_ms=source_ack_ms)
    folder = start_run(boards, run_id, meta)
    for name, d in dumps.items():
        (folder / f"config_{name}.txt").write_text("\n".join(d) + "\n", encoding="utf-8")

    status = "ok"
    try:
        ev("sink_start")
        sink.cmd("exp start", expect=r"started")
        time.sleep(1.0)
        relay.cmd("exp start", expect=r"started")
        time.sleep(1.0)
        m_src = src.mark()
        t0 = time.monotonic()
        ev("source_start")
        src.cmd(f"exp start {count}", expect=r"started")
        if outage_s is not None:
            time.sleep(max(0.0, 30.0 - (time.monotonic() - t0)))
            ev("outage_start")
            sink.cmd("exp stop", expect=r"stopped")
            time.sleep(outage_s)
            ev("outage_end")
            sink.cmd("exp start", expect=r"started")
        planned = int(count * interval_ms / 1000) + (outage_s or 0) + 60
        done = src.wait_for(r"STOP: .*reason=count_reached", m_src, planned + timeout_extra_s)
        if done is None:
            status = "timeout"
        ev("source_stopped" if done else "timeout")
        time.sleep(tail_s)
        # Final state of the relay store (one poll after the timed part).
        m = relay.mark()
        relay.send("exp status")
        time.sleep(1.5)
        events["relay_status_after"] = [ln for ln in relay.since(m)
                                        if "depth=" in ln or "generated=" in ln]
    except Exception as err:  # keep the logs, mark the run
        status = f"error: {err}"
    finally:
        for b in (src, relay, sink):
            try:
                b.cmd("exp stop")
            except Exception:
                pass
        time.sleep(1.5)
        counters = {}
        for name, b in boards.items():
            try:
                m2 = b.mark()
                b.send("exp status")
                time.sleep(1.5)
                counters[name] = [ln for ln in b.since(m2) if "generated=" in ln or "retries=" in ln]
            except Exception as err:
                counters[name] = [f"error: {err}"]
        events["counters_after"] = counters
        meta["status"] = status
        end_run(boards, folder, events, meta)
    return {"run_id": run_id, "status": status, "folder": str(folder)}


SCENARIOS = {
    "R1_custody_60": dict(custody=True, count=60, outage_s=None,
                          notes="60 frames, custody, no outage"),
    "R2_custody_outage60": dict(custody=True, count=180, outage_s=60,
                                notes="custody, sink stopped for 60 s from t=30 s"),
    "R3_openloop_60": dict(custody=False, count=60, outage_s=None,
                           notes="open-loop, no outage"),
    "R4_openloop_outage30": dict(custody=False, count=150, outage_s=30,
                                 notes="open-loop, sink stopped for 30 s from t=30 s"),
    "R5_custody_outage5": dict(custody=True, count=125, outage_s=5,
                               notes="custody, short outage: detection and re-up"),
    "O1_overflow330": dict(custody=True, count=450, outage_s=330, tail_s=30,
                           notes="custody, 330 s sink outage (longer than the relay store)"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--sink", required=True)
    ap.add_argument("--relay", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--runs", default="R1_custody_60", help="comma list; names: " + ", ".join(SCENARIOS))
    ap.add_argument("--neighbours", action="store_true", help="run the HELLO receive check first")
    ap.add_argument("--out", default=None, help="output root (default data/dryrun/harness_runs)")
    args = ap.parse_args()
    global OUT_ROOT
    if args.out:
        OUT_ROOT = Path(args.out)

    boards = {"sink": Board("sink", args.sink), "relay": Board("relay", args.relay),
              "source": Board("source", args.source)}
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        time.sleep(1.0)
        for b in boards.values():
            b.send("")
        time.sleep(0.5)
        read_ids(boards)
        print("ids:", {n: b.node_id for n, b in boards.items()}, flush=True)
        for b in boards.values():
            b.cmd("exp factory", expect=r"profile erased")
        if args.neighbours:
            configure(boards, custody=True)
            nb = neighbours_ok(boards)
            (OUT_ROOT / "neighbours.json").write_text(json.dumps(nb, indent=2), encoding="utf-8")
            print("neighbours:", json.dumps(nb), flush=True)
        for name in [r.strip() for r in args.runs.split(",") if r.strip()]:
            sc = dict(SCENARIOS[name])
            print(f"--- {name} start {host_ts()}", flush=True)
            res = run_scenario(boards, name, **sc)
            print(f"--- {name} {res['status']} {host_ts()}", flush=True)
            results.append(res)
    finally:
        for b in boards.values():
            b.close()
    (OUT_ROOT / "last_harness_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
