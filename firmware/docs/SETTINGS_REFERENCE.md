# Settings

Every setting can be changed while the node is idle with `exp sett <key> <value>`. `exp sett` alone prints all keys with their current values. The defaults come from `firmware/Kconfig` (see [`KCONFIG_REFERENCE.md`](KCONFIG_REFERENCE.md)). The last column shows what the paper's runs used. Settings marked with * can only be changed while the node is stopped.

## Traffic

| Key | What it controls | Default | Paper's runs |
|---|---|---|---|
| `role` | `source`, `relay` or `sink` (also `exp role <name>`) | chosen after boot | one per board |
| `dest` | node id the source sends to | 0 | the sink's id |
| `interval` | time between frames at the source, in ms (0 = send nothing) | 1000 | 1000 |
| `count` | number of frames to create (0 = until stopped) | 0 | set with `exp start <N>` |
| `size` | application payload in bytes | 64 | 16 at the source |
| `class` | class of generated frames, `tel` or `alarm` | `tel` | `tel` |
| `ttl` | hop limit of a frame | 5 | 5 |
| `power` | TX power index from 0 to 13 (the mapping to dBm is not known) | 10 | source 1, relay 10, sink 10 |
| `mcs` | modulation and coding scheme | 0 | 0 |

## Custody and the store

| Key | What it controls | Default | Paper's runs |
|---|---|---|---|
| `custody` | `on` uses ACKs, retries and link states. `off` sends each frame once (open-loop) | on | on, and off for the baseline |
| `ack_timeout` | how long to wait for an ACK after sending, in ms | 200 | relay 200, source 400 |
| `attempts` | sends of one frame before the link is declared DOWN | 4 | 4 |
| `backoff_min`, `backoff_max`, `backoff_cap` | random wait before a retry. The first retry waits between `min` and `max`, and the upper limit doubles each time up to `cap` (ms) | 10, 20, 80 | the same |
| `nack_holdoff` | how long to wait after a "queue full" or "no route" answer, in ms. The wait doubles when the receiver has no free slot at all | 1000 | 1000 |
| `gap` | listening time after a completed exchange, in ms | 20 | relay 5, source 35, sink 20 |
| `policy` | what a full store does: `reject` refuses the new frame (the sender keeps it), `drop_oldest` throws away the oldest telemetry frame | `reject` | `reject` |
| `tel_ttl` | stored telemetry older than this is dropped, in ms (0 = keep) | 600000 | 600000 |
| `dedup` | ignore frames that were already delivered | on | on |
| `stream_idle` | how long a source can be silent before the duplicate memory forgets it, in ms | 1800000 | 1800000 |
| `direct` | with no route entry, send straight to the destination | on | off at the source, on at relay and sink |
| `assume_up` | treat a new next hop as UP without probing it | off | off |

The size of the store (320 slots of 64 bytes, 32 of them for alarms) is a build option: `SF_SMALL_SLOTS` and `SF_SMALL_ALARM_SLOTS`.

## Link state

| Key | What it controls | Default | Paper's runs |
|---|---|---|---|
| `hello` | time between HELLO frames, in ms (0 = off) | 2000 | 2000 |
| `hello_tx` | who sends HELLO: `auto` (relay and sink), `on` or `off` | `auto` | relay and sink `on`, source `auto` |
| `hello_dead` | an UP link goes DOWN after this much silence from a neighbour that was heard before, in ms (0 = off) | 7000 | 7000 |
| `hold_min`, `hold_max` | the first hold-down and its upper limit, in ms. The hold-down doubles with each failure in a row | 5000, 60000 | the same |
| `hold_reset` | how long a link must stay UP before the hold-down starts from the beginning again, in ms | 60000 | 60000 |
| `t_probe` | extra wait before probing starts, in ms | 3000 | 3000 |
| `hold_cancel` | a frame heard after this much silence ends the hold-down at once, in ms (0 = off) | 3000 | 3000 |
| `probe_fast` | time between probes, in ms | 200 | 200 |
| `n_up` | probe replies in a row needed before the link is UP | 3 | 3 |
| `liveness`* | `any` counts every frame from a neighbour as a sign of life, `hello` counts only HELLO frames | `any` | `any` |

## Radio

| Key | What it controls | Default | Paper's runs |
|---|---|---|---|
| `cancel_ack` | stop waiting for an ACK as soon as one arrives | on | on |
| `rx_mode`* | `event` listens in one long receive that the node ends itself, `slice` listens in short slices | `event` | `event` |
| `rx_slice` | length of one slice in ms | 15 | 15 |
| `ctrl_subslots`* | PHY length of HELLO, ACK and PROBE frames in subslots (4, 8 or 16) | 8 | 8 |
| `rssi_level` | RSSI level passed to the modem's receiver, in dBm | -60 | -60 |

## Alarms

| Key | What it controls | Default |
|---|---|---|
| `alarm_rate`, `alarm_burst` | how fast `exp alarm` tokens refill per second and how many can be saved up (rate 0 turns alarms off) | 5, 10 |

Alarm frames were not used in the measurements. The shell commands are listed in [`SHELL_COMMANDS.md`](SHELL_COMMANDS.md).
