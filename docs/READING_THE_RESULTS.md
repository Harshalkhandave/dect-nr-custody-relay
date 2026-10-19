# Reading the results

`python tools/analysis/e1_analyze.py --root data/E1_outage_sweep_v2` recomputes every per-run result, `E1_runs.csv` and `E1_summary.md` from the raw logs. It also draws three plots into a `figures/` folder next to them: the lost frames against the outage length, the re-up time against the outage length, and the predicted against the measured drain time. The analysis only reads the raw logs and manifests. It never changes them.

## What is in a run folder

The folders are in `data/E1_outage_sweep_v2/` and are named like `E1_custody_D060_r01`. That is: mode (`custody` or `openloop`), outage length D in seconds, and repetition number.

| File | What it holds |
|---|---|
| `source.txt`, `relay.txt`, `sink.txt` | the console log of each board, with the host's clock in front of every line (see [`../firmware/docs/LOG_REFERENCE.md`](../firmware/docs/LOG_REFERENCE.md)) |
| `config_source.txt`, `config_relay.txt`, `config_sink.txt` | all settings of the board, read back before the run (`exp sett`) |
| `manifest.json` | information about the run: run id, mode, number of frames, outage length, source interval, payload, MCS, TX powers, ACK timeouts, gaps, whether the boards were rebooted, start and end time, the boot lines of each board (firmware revision, SDK, modem firmware), node ids, serial ports and a copy of `data/SETUP.json` |
| `events.json` | the host's time stamps of the commands (`sink_start`, `source_start`, `outage_start`, `outage_end`, `source_stopped`) and the status lines read at the end |
| `meta_start.json` | information written when the run started |
| `result_e1.json` | the result of the analysis for this run |

`schedule.json` in the same folder holds the seed and the order of the runs.

## How the numbers are defined

- **Unique PDR** (`unique_pdr`): frames delivered at the sink divided by frames the source created. It is computed from the node counters whenever they are available (`pdr_counter_based`). The version computed from the log lines is kept as `pdr_log` in `result_e1.json`. The sink's counters start from zero after it is restarted, so the sink total is the sum of the `delivered` value in the `SUMMARY` lines printed at each stop. Runs where the console log lost lines (so the counters and the log disagree) get the flag `log_lossy`.
- **Detection time**: from the moment the sink is stopped to the relay's first `LINK_STATE ... new=DOWN` for its link to the sink.
- **Re-up time**: from the moment the sink is started again to the first `new=UP`.
- `detection_dev_s` and `reup_dev_s` use the boards' own clocks. The sink's stop and start times are converted to the relay's clock with a linear fit on forwarded DATA frames. `detection_s` and `reup_s` use the host's time stamps, which come out 0.16 to 0.27 s larger.
- **Backlog** (`B_at_up`): frames in the relay's store when the link first comes UP after the restart.
- **Drain time** (`drain_s`): from that moment until the relay's store is empty.
- **Service rate**: `mu_pkt_s` is the number of ACKs received while draining divided by the drain time. It also counts ACKs for frames that arrived during the drain, so the prediction `T_d_pred_s` (= B / (mu - lambda), with lambda = 1 frame/s) matches the measured time by construction. `mu_cycle_pkt_s` is the independent estimate: 1 divided by the median time between consecutive ACKs during the drain, leaving out gaps above 150 ms (those contain retransmissions). `T_d_pred_cycle_s` and `T_d_error_cycle_pct` use it. The drain-model error in the paper is the median of the absolute `T_d_error_cycle_pct` for each outage length.
- `penalty_per_arrival_s`: the measured drain time minus the prediction from `mu_cycle_pkt_s`, divided by the frames that arrived during the drain (`arrivals_in_drain`).

## `E1_runs.csv`

One row per run. The columns are: `run_id`, `mode`, `outage_s`, `count` (frames the source created), `sent_unique`, `delivered_unique`, `lost_count`, `unique_pdr`, `pdr_counter_based`, `duplicate_deliveries`, the four time columns above, `B_at_up`, `relay_peak_pending`, `drain_s`, the rate and prediction columns above, `relay_link_down_events`, `relay_queue_full_nacks`, `source_peak_depth` and `flags`.

## Statistics

For each condition the paper reports the mean of the per-run values with a 95% bootstrap confidence interval of that mean (10,000 resamples, seed 1). The run is the unit of inference. No run was removed.

## Other data

| Path | What it holds |
|---|---|
| `data/dryrun/setup_check_power2_2026-10-12/` | short runs at source TX power index 1, 2, 3, 4 and 10, used to see whether the sink hears the source directly (frames with `hop=0`) |
| `data/sweep_guard/guard.log` | the link-quality guard of the sweep: the relay's RSSI of the source for each run, board temperatures and frames heard directly. The sweep ran in two sessions: the guard ended the first one early on Oct 12 (after 44 runs, `SWEEP ENDED early: link guard`) and the sweep was resumed on Oct 13 |
| `data/E1_outage_sweep_v2/sweep.log` | the progress log of the sweep driver for the second session (Oct 13) |
| `data/SETUP.json` | where the boards stood, the distances (estimates) and notes. `data/SETUP_TEMPLATE.json` is the empty form |
| `data/MANIFEST_TEMPLATE.json` | the empty form of a run's metadata |

## Limits of the measurements

- One room, one relay, three boards, one traffic rate (1 frame per second), a 16-byte payload and MCS 0.
- The outage is created by stopping the sink node. This ignores fading and marginal links.
- The sink did not hear the source directly, except for two frames in one run. The margin of source TX power index 1 was not measured.
- The detection time of about 1 s follows from four sends with the relay's 200 ms ACK timeout, and from the stop happening at about the same point of the traffic in every run.
- The drain-time model missed its 15% target at three of the five outage lengths.
