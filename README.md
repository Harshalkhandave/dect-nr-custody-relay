# Outage-Resilient Hop-by-Hop Custody for Telemetry Relay on a PHY-Only DECT-2020 NR Stack (nRF9151)

This repository contains the firmware, tools and raw data behind the paper of the same title.

## The idea in short

On Nordic's PHY-only DECT NR+ stack, a relay has no acknowledgments, no retries and no buffer. If its next hop disappears, every frame that arrives in the meantime is lost.

We put a small custody layer on top of the PHY API. Each node keeps a frame in a RAM store, sends it, waits for an ACK from the next hop and only then lets go of it. A simple link state (DOWN, PROBING, UP) decides when sending starts again after an outage.

To test it, three Conexio Stratus Pro boards form a chain: source, relay, sink. The source sends one frame per second. The sink is stopped for 5 to 330 seconds and started again. We repeat this with custody and without it (open-loop, which is the same firmware with custody switched off).

- With custody, no frame was lost in 50 of 50 runs, even when the outage was longer than the relay's store. The source kept the frames that did not fit.
- Open-loop delivered 0.945 of the frames for 5 s outages and 0.262 for 330 s outages.
- With custody, the link came up again 0.48 s on average after the sink came back.

All results come from one room, one relay and emulated outages.

## Where to find things from the paper

| In the paper | In this repository |
|---|---|
| Section III, System | [`firmware/`](firmware/README.md), [`firmware/docs/LINK_STATE.md`](firmware/docs/LINK_STATE.md), [`firmware/docs/WIRE_FORMAT.md`](firmware/docs/WIRE_FORMAT.md) |
| Table I, setup | [`docs/RUNNING_THE_EXPERIMENT.md`](docs/RUNNING_THE_EXPERIMENT.md), [`firmware/docs/SETTINGS_REFERENCE.md`](firmware/docs/SETTINGS_REFERENCE.md), `data/SETUP.json` |
| Section IV, Method | [`docs/RUNNING_THE_EXPERIMENT.md`](docs/RUNNING_THE_EXPERIMENT.md), `tools/run_sweep.py`, `tools/harness/` |
| Section V, Table II and Fig. 2 | [`docs/READING_THE_RESULTS.md`](docs/READING_THE_RESULTS.md), `data/E1_outage_sweep_v2/` (`E1_summary.md`, `E1_runs.csv`, one folder per run) |
| Section VI, limits | [`docs/READING_THE_RESULTS.md`](docs/READING_THE_RESULTS.md) (measurements), [`firmware/docs/LIMITATIONS.md`](firmware/docs/LIMITATIONS.md) (firmware) |

## Where to start

- To read or use the firmware, start with [`firmware/README.md`](firmware/README.md). It links to the build steps, the options, the shell commands, the settings, the frame format and the log format.
- To see how the tests were run, read [`docs/RUNNING_THE_EXPERIMENT.md`](docs/RUNNING_THE_EXPERIMENT.md).
- To understand the results and the data files, read [`docs/READING_THE_RESULTS.md`](docs/READING_THE_RESULTS.md).
- To recompute the tables from the raw logs, run `python tools/analysis/e1_analyze.py --root data/E1_outage_sweep_v2`.

There are no prebuilt firmware images. Build from source as described in [`firmware/docs/BUILD_AND_FLASH.md`](firmware/docs/BUILD_AND_FLASH.md).

## What is in each folder

| Folder | Contents |
|---|---|
| `firmware/` | the firmware and its documentation |
| `docs/` | how the tests were run and how to read the results |
| `data/` | raw logs, settings and results of the 100 runs, the placement of the boards, the source power check and the guard log |
| `tools/` | the sweep driver (`run_sweep.py`), the run harness (`harness/`), the analysis (`analysis/`), a serial logger (`logger/`) and a build script |

## License

Apache-2.0, see [`LICENSE`](LICENSE).
