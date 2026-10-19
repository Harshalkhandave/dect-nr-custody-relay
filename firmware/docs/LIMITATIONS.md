# Limitations

What the firmware does not do, and a few things to be careful about. The limits of the measurements are in [`../../docs/READING_THE_RESULTS.md`](../../docs/READING_THE_RESULTS.md).

## Firmware

- **The store lives in RAM only.** When a node reboots, every stored frame is gone. Only the settings (after `exp save`) and the boot counter are kept in flash.
- **One frame at a time.** A node has a single DATA or PROBE frame on its way. Draining a backlog therefore goes at the speed of one send and one ACK per frame.
- **Size of the store.** 320 slots, of which 32 are reserved for alarms and 288 are for telemetry. With the `reject` policy a full store refuses new frames and the sender keeps them. Stored telemetry older than 600 s is dropped.
- **Duplicates.** A node remembers the highest sequence number from each source and class, not a window of numbers. It expects frames in order.
- **Counters restart.** `exp start` sets all counters to zero. If a node is stopped and started again during a run, the total for the run is the sum of the readings before the stop and at the end.
- **Small queues.** Up to 4 ACKs can wait to be sent and up to 8 received frames can wait to be processed. If the receive queue is full, frames are dropped and counted (`rx_queue_drop` in `exp status`). It was 0 in every recorded status line of the sweep.
- **Alarms** (the priority class) exist but were not used in the measurements.
- **The console log** is buffered (32 KB) and runs at 115200 baud. In very fast drains it can drop lines. The counters stay correct.

## Code notes

- There is no watchdog and no reset after a fatal error. If the board halts before the shell starts, nothing is printed.
- A modem timeout or a receive error stops the node.
- `wait_boot` in `main.c` waits without a time limit, so a modem that never answers keeps the main thread waiting.
- `frame_end_ms` in `main.c` is a 64-bit value shared between the modem callback and the radio thread without a lock. On a 32-bit core a read could be torn.
- The real stack use of each thread has not been measured.

## Radio

- **TX power index.** The index goes from 0 to 13, and its mapping to dBm is not known. The modem reports 21 dBm as the maximum for its power class, but that is a ceiling and not the power of any index.
- **Listen-before-talk.** The radio listens before every transmission (maximum listening period), but the RSSI threshold is 0 dBm, so it never decides that the channel is busy. The project makes no claim of regulatory compliance.
- **Carrier.** The US overlay uses carrier 1711 in the 1.9 GHz band. Check the rules of your region.
- **Modem firmware.** The measurements used `mfw-nr+_nrf91x1_1.1.0`. Another version could change the timing.
