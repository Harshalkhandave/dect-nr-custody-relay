# How the firmware is organized

This guide explains how the code is put together and how one frame travels through it. It points to functions by name, so you can find them with a text search in `firmware/src`.

## 1. The big picture

Every board runs the same image, and the role you pick at run time (source, relay or sink) decides what it does.

- The source creates a frame once a second and puts it in a RAM store.
- The radio sends the oldest stored frame to the next hop and waits for an ACK. Only when the ACK arrives does the node remove the frame from its store. That is custody.
- A relay stores what it receives, answers with an ACK and forwards the frame the same way.
- If the next hop stops answering, the frame stays in the store and a link state machine (DOWN, PROBING, UP) decides when to try again.
- The sink counts the frame as delivered and sends an ACK.

All protocol decisions live in one file that never touches hardware (`sf_node.c`). The other files move bytes around.

## 2. The files

| Layer | File | What it does |
|---|---|---|
| Radio and threads | `main.c` | starts the modem, runs the radio thread, handles the modem callbacks, calls the modem's send and receive |
| Connection to Zephyr | `sf_port.c` | holds the lock, the receive queue and the Kconfig defaults, and wraps every call into the protocol code |
| | `sf_shell.c` | the `exp` shell commands |
| | `sf_persist.c` | saved settings and the boot counter ("epoch") in flash |
| Protocol code | `sf_node.c` | everything a node decides. It makes no Zephyr calls |
| | `sf_link.c` | the link state machine for each neighbour |
| | `sf_store.c` | the RAM store for frames that wait for custody |
| | `sf_dedup.c` | duplicate detection |
| | `sf_codec.c` | frame bytes to a structure and back |
| Small helpers | `sf_phy.h`, `sf_rxpolicy.h`, `sf_types.h`, `sf_node.h` and others | the PHY length rule, the rule for ending a receive, shared types |

The protocol files also compile on a PC, which is how `firmware/tests/host_test.c` can test them without a board (see [`TESTING.md`](TESTING.md)).

## 3. Threads and how they talk

| Context | Where it starts | What it does |
|---|---|---|
| main thread | `main` in `main.c` | runs once at boot: reads the device id, starts `sf_port_boot` (settings and boot counter), starts the modem, creates the radio thread and returns. Its stack is 2048 bytes (`prj.conf`) |
| radio thread | `radio_thread` in `main.c` | the heart of the firmware. It asks the protocol code what to do, sends or listens, and hands received frames to the protocol code. It is the only thread that calls the modem's send. Priority 5, 8192-byte stack (`SF_RADIO_STACK`) |
| shell thread | `cmd_*` in `sf_shell.c` | runs your `exp` commands. It only changes settings or starts and stops the node, through `sf_port_*` functions. Stack 3072 bytes |
| modem callback | `dect_phy_event_handler` in `main.c` | called by the modem library when a send or receive finishes or a frame arrives. It must not block, so it only copies the frame into a queue and releases semaphores |
| log thread | Zephyr's | prints the buffered log lines, waking every 50 ms |

The Nordic documentation that was available does not say which thread the modem library uses to call the callback. The code therefore treats the callback as a place that must never block, and uses a spinlock there (see `sf_port_on_pdc` in `sf_port.c`).

How they share data:

- **The node lock.** A mutex in `sf_port.c` protects the whole node state. Every `sf_port_*` function that touches the protocol code takes it. The radio thread and the shell thread both use it.
- **The receive queue** (8 frames). The modem callback puts frames in (`sf_port_on_pdc`) and the radio thread takes them out (`sf_port_drain_rx`). It uses a spinlock because the callback cannot wait for a mutex.
- **Semaphores** in `main.c`: `op_sem` (a modem operation finished), `frame_sem` (a frame arrived), `ack_sem` (an ACK arrived), `wake_sem` (a shell command changed something). `sf_run_sem` in `sf_port.c` starts the radio loop.
- **Three values the callback reads without the lock**: `cancel_ack`, `ctrl_subslots` and `rssi_level`. `sync_runtime` copies them into atomic variables.

## 4. The main loop

The radio thread repeats these steps:

1. `sf_port_poll` takes the lock and calls `sf_node_poll`. The answer is an action: either send these bytes, or listen for N milliseconds.
2. To send, `transmit` calls the modem and `wait_op` waits until the modem reports it is done. Then `sf_port_on_tx_done` tells the protocol code.
3. To listen, `receive` starts the modem's receive. The thread waits in one of three ways: `rx_idle_wait` (idle listening, ended by a frame, a shell command or the next deadline), `wait_rx_or_ack` (waiting for an ACK, ended as soon as an ACK arrives) or plain `wait_op`.
4. Frames that arrived are passed to `sf_node_on_rx` by `sf_port_drain_rx`.

`sf_node_poll` picks the next action in a fixed order:

1. Housekeeping: finish a counted run, expire old frames, clean up the duplicate memory, create a frame if one is due (`maybe_generate`) and advance the link timers.
2. If an ACK is waiting to be sent, send it first. Answering a neighbour has priority.
3. If a retry is waiting out its backoff, wait. If an ACK timeout has passed, retry or, after the last attempt, fail the link (`service_timeout`).
4. If a frame is waiting for its ACK, listen for it.
5. If the short pause after an exchange has not ended, listen.
6. Send a HELLO if one is due, then a PROBE for a link that is probing.
7. Send the oldest stored frame, if its link is UP and no refusal hold-off applies (`arm_data`).
8. Otherwise listen until the next deadline (`idle_listen_ms`).

A node has only one DATA or PROBE frame on its way at a time (stop-and-wait). That is why draining a backlog takes about 28 ms per frame.

## 5. One frame's journey (custody on)

1. The source creates a frame in `maybe_generate` and `enqueue_local` puts it into the store with `sf_store_put`.
2. When the link to the relay is UP, `arm_data` marks the frame as in flight and the radio thread sends it (log line `TX ... retx=0`).
3. After the send, `sf_node_on_tx_done` starts the ACK timer.
4. At the relay, the modem callback `on_pdc` passes the frame to `sf_port_on_pdc`, which queues it and releases `frame_sem`.
5. The relay's radio thread calls `sf_node_on_rx`, which calls `handle_data`. This checks that the frame is for this node, checks for duplicates (`sf_dedup_check`) and calls `take_custody`, which puts the frame in the relay's store, logs `STORED` and queues an ACK (`queue_ack`).
6. The relay sends the ACK first. At the source, the callback releases `ack_sem` (when `cancel_ack` is on).
7. The source ends its receive at once (`wait_rx_or_ack`) and `handle_ack` removes the frame from the store (`sf_store_pop_order`). Custody has moved to the relay (log line `ACK_RX ... rtt_us=`).
8. The relay repeats the same steps toward the sink. The sink's `handle_data` calls `accept_sink`, which counts the frame, logs `DELIVER` and sends the ACK.

## 6. When the next hop stops answering

- After `ack_timeout` the node retries with a random backoff, and each retry logs `RETRY`. After the last attempt (`attempts`, 4), `fail_inflight` calls `sf_link_fail` and the link goes DOWN (`LINK_STATE ... reason=max_attempts`). The frame stays in the store.
- New frames keep arriving and are stored (`STORED depth=...`). If the store is full, the node answers `QUEUE_FULL` and the node upstream keeps the frame in its own store (see `handle_ack`).
- The link states and timers are explained in [`LINK_STATE.md`](LINK_STATE.md).
- When the link is UP again, the stored frames are sent one at a time. This is called draining the store.

## 7. The store, duplicates and routes

- **Store** (`sf_store.c`). Two RAM pools, no `malloc`. By default there are 320 small slots of 64 bytes: 288 for telemetry and 32 reserved for alarms. Each slot has an order number, and the oldest frame whose link is ready goes first (`sf_store_peek`). Telemetry older than 600 s is dropped (`sf_store_expire`). The store is RAM only, so a reboot empties it.
- **Duplicates** (`sf_dedup.c`). For each source and class the node remembers the highest sequence number it has accepted. If an ACK was lost and the sender sends the frame again, the node answers `DUPLICATE` and does not deliver it twice (see `handle_data`).
- **Routes** (`resolve_next` in `sf_node.c`). A small table maps a destination to a next hop. With the `direct` setting on, a frame without a route entry goes straight to its destination.

## 8. Boot and the shell

- `main` reads the device id, calls `sf_port_boot` (defaults from Kconfig, settings storage, the boot counter written with `sf_persist_boot_epoch`, an optional saved profile, `sf_node_init`), then `boot_phy` (modem library, PHY init, configure and activate), creates the radio thread and prints `idle`.
- `exp start` runs `cmd_start`, `sf_port_start` and `sf_node_start`, then wakes the radio thread, which was waiting in `sf_port_wait_until_started`.
- `exp sett <key> <value>` runs `cmd_sett`, `sf_port_set` and `sf_node_set`, then `sync_runtime` and `radio_wake` so a sleeping receive notices the change.
- `exp reboot` runs `sf_port_reboot`: stop, print one line, wait 50 ms, restart the board.

## 9. One image, several behaviours

Several behaviours are runtime settings: `custody` on or off (off sends once with no ACK, see `arm_data`), `cancel_ack`, `rx_mode` (event or slice), `liveness` (any or hello), `ctrl_subslots` (4, 8 or 16), `rssi_level`, `hold_cancel` and the timers. `exp sett` lists them all (see [`SETTINGS_REFERENCE.md`](SETTINGS_REFERENCE.md)). `ctrl_subslots`, `rx_mode` and `liveness` cannot be changed while the node is running.

## 10. Log lines

Every event goes through `emit` and `LOG_INF` in `sf_port.c`. The lines are explained in [`LOG_REFERENCE.md`](LOG_REFERENCE.md).
