# Log lines

The firmware prints one line for every protocol event on the console. The serial logger and the run harness add the host's clock in front of each line (`[hh:mm:ss.mmm]`), and the board adds its own uptime (`[hh:mm:ss.mmm,uuu]`).

Inside a line, `time=` is the node's uptime in milliseconds and `time_us=` is the same in microseconds. The analysis uses `time_us` to measure durations on one board and lines the boards up with a linear fit on forwarded frames.

The log is deferred and has a 32 KB buffer, so during a very fast drain the console can drop lines. That is why the counters (`exp status`, `SUMMARY`) are the reliable count.

## Lines the analysis reads

| Line | When it appears | Main fields |
|---|---|---|
| `START`, `STOP` | the node starts or stops | role, `count`, `custody` (1 = on), `epoch`, `time_us`. `STOP` also has a `reason` (`user` or `count_reached`) |
| `SUMMARY` | at every stop | the counters: `generated`, `delivered`, `stored`, `drained`, `dropped_*`, `rejected_*`, `retries`, `dup_rx`, `rx_gap`, `epoch` |
| `TX` | a frame is sent | `type` (DATA, HELLO or PROBE), `seq`, `src`, `dst`, `prev`, `next`, `hop`, `ttl`, `class`, `epoch`, `retx` (0 for the first send, 1 for a retry, with the `attempt` number), `time_us` |
| `RX` | a frame is received | the same fields plus `rssi` in dBm. DATA frames are always logged. HELLO, ACK and PROBE frames only with the `SF_LOG_RX_CTRL` option |
| `STORED` | a frame enters the store | `seq`, `src`, `class`, `depth` (frames in the store) |
| `ACK_TX` | an ACK is queued for sending | `status`, `seq`, `len` |
| `ACK_RX` | the ACK for our frame arrives | `status`, `seq`, `from`, `rtt_ms`, `rtt_us` (from the end of our transmission until the ACK is processed) |
| `RETRY` | no ACK arrived in time | `seq`, `attempt`, `backoff_ms` |
| `LINK_STATE` | a link changes state | `next` (the neighbour), `old`, `new`, `reason`, `time_us` |
| `DELIVER` | the sink counts a frame | `seq`, `src`, `prev`, `hops`, `rssi`, `class`, `epoch`, `time_us` |

The `reason` of a `LINK_STATE` line is one of: `probes` (three probe replies, PROBING to UP), `max_attempts` (four failed sends), `hello_dead` (silence while UP), `t_probe` (probe timer ran out, DOWN to PROBING), `hello` (a frame was heard while DOWN), `returned` (a silent neighbour came back, which ends the hold-down), `neighbor_reset` (the neighbour rebooted). See [`LINK_STATE.md`](LINK_STATE.md).

## Other lines

| Line | Meaning |
|---|---|
| `NACK_TX`, `NACK_RX` | a frame was refused (`QUEUE_FULL` or `NO_ROUTE`). `NACK_RX` shows `hold_ms`, the wait before the next try |
| `DROP_TTL`, `DROP_EXPIRED` | the hop limit was reached, or a stored telemetry frame was older than its time limit |
| `CUSTODY_BROKEN` | the oldest frame was dropped to make room (only with the `drop_oldest` policy) |
| `RX_GAP`, `SRC_RESET` | a receiver saw a gap in the sequence numbers, or a source rebooted (its boot counter changed) |
| `NEIGHBOR_RESET` | a neighbour's boot counter changed |
| `BAD_FRAME` | a received frame could not be decoded |
| `FLUSH` | stored frames were dropped (at the start of a run, on a role change or with `exp flush`) |
| `BOOT_INFO`, `BOOT_MODEM` | printed at every boot: the firmware revision, SDK and Zephyr versions, stack sizes and carrier, and the modem firmware version, hardware, UUID, temperature and supply voltage |
