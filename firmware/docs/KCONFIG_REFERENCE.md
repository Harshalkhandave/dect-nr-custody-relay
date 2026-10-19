# Kconfig reference

Build-time options of the firmware (`firmware/Kconfig`). Each option is set as `CONFIG_<NAME>` in `prj.conf`, in an overlay (see `OVERLAYS.md`) or on the build command line. Most of them are also runtime settings of the `exp sett` shell command (see `SETTINGS_REFERENCE.md`); the Kconfig value is the default after boot.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `CONFIG_CARRIER` | int | 0 | Carrier number. Required. Set this in overlay-us.conf or overlay-eu.conf. Band index 1 is used only for carriers 525..551. This is build-time because it is a regulatory choice, not a lab knob. |
| `CONFIG_NETWORK_ID` | int | 91 | DECT network id (range 1 4294967295). Build-time. Both the PHY header short id and the modem network id use this value. Do not change it on one board only. |
| `CONFIG_TX_POWER` | int | 10 | Default TX power index (0..13) (range 0 13). Starting value for exp sett power. Not dBm. Overlays may override it. Runtime changes apply to the next transmission. |
| `CONFIG_MCS` | int | 0 | Default MCS (range 0 7). Starting value for exp sett mcs. The measurements used MCS 0. |
| `CONFIG_SF_PHY_MTU` | int | 249 | Maximum PHY payload (bytes) (range 32 249). Total on-air application PDU, header included. 249 is the largest size that was put on the air at MCS 0. The 18-byte protocol header is inside this budget, so the largest application payload is MTU - 18. |
| `CONFIG_SF_RX_FILTER_ID` | int | 0 | PHY RX filter receiver identity (range 0 65535). 0 accepts every receiver identity (broadcast filter). |
| `CONFIG_SF_HARQ_RX_PROCESSES` | int | 4 | Modem HARQ RX process count (range 1 8) |
| `CONFIG_SF_HARQ_RX_EXPIRY_US` | int | 5000000 | Modem HARQ RX expiry (microseconds) |
| `CONFIG_SF_DEVICE_ID_OVERRIDE` | bool | n | Override the hardware device id |
| `CONFIG_SF_DEVICE_ID` | int | 1 | Device id override (range 1 65534). Normally the id is the first two bytes from hwinfo. Override only for a bench that must use fixed ids. |
| `CONFIG_SF_ROLE_SOURCE` | bool | - | source |
| `CONFIG_SF_ROLE_RELAY` | bool | - | relay |
| `CONFIG_SF_ROLE_SINK` | bool | - | sink |
| `CONFIG_SF_DEST_ID` | int | 0 | Default destination id (range 0 65535). 0 means unset. A source will not start until exp sett dest or a profile. |
| `CONFIG_SF_PAYLOAD_LEN` | int | 64 | Default application payload (bytes) (range 1 231). This is the application payload, not the on-air frame. The frame is this value plus the 18-byte header. It must fit CONFIG_SF_SMALL_PAYLOAD, or the large pool when that is enabled. |
| `CONFIG_SF_INTERVAL_MS` | int | 1000 | Default source period (ms) (range 0 600000). 0 turns the periodic generator off. Use exp alarm, or set a period. |
| `CONFIG_SF_COUNT` | int | 0 | Default packet count (0 = until stop) (range 0 4294967295) |
| `CONFIG_SF_HELLO_MS` | int | 2000 | Default HELLO period (ms, 0 = off) (range 0 600000) |
| `CONFIG_SF_TTL` | int | 5 | Default hop limit (range 1 16) |
| `CONFIG_SF_DIRECT_FALLBACK` | bool | y | If no route entry, send straight to the destination id. Turn off when the source must be forced through exp route. Runtime: exp sett direct on/off. A saved profile overrides this default. |
| `CONFIG_SF_ASSUME_UP` | bool | n | Treat a new next hop as UP without probing. Off matches the protocol rule that a link becomes UP only after N probes. Turn on for a bench that should move data immediately. Runtime: exp sett assume_up on/off. |
| `CONFIG_SF_DEDUPE` | bool | y | Drop duplicate deliveries. Off delivers every copy. Leave it on unless you are deliberately testing the duplicate path. Runtime: exp sett dedup on/off. |
| `CONFIG_SF_CUSTODY` | bool | y | Hop-by-hop custody (ACK, retry, link-state gating). Off selects open-loop mode: each stored frame is sent once, no ACK is waited for or sent, the slot is released at once, and link state does not gate sending (no PROBE frames). All nodes in a run must use the same setting. Runtime: exp sett custody on/off, only while stopped. |
| `CONFIG_SF_LIVENESS_ANY_FRAME` | bool | y | Any frame from a neighbour counts as proof of life. On: every frame heard from a neighbour refreshes its liveness (HELLO, ACK, PROBE, DATA, also overheard ones). A node sends a HELLO only if it has transmitted nothing for a HELLO interval (and once at start), and links are reset on every start. Off: only HELLO refreshes liveness, HELLOs are periodic, and links survive a stop and start. |
| `CONFIG_SF_GEN_CLASS_ALARM` | bool | n | Periodic generator sends alarm instead of telemetry |
| `CONFIG_SF_POLICY_REJECT` | bool | - | reject (ACK QUEUE_FULL, sender keeps the packet) |
| `CONFIG_SF_POLICY_DROP_OLDEST` | bool | - | drop oldest telemetry already in this store |
| `CONFIG_SF_HELLO_TX_ON` | bool | n | Send HELLO even from a source. When off, HELLO follows the role: relay and sink send it, source does not. Runtime exp sett hello_tx auto/on/off replaces this. |
| `CONFIG_SF_SMALL_SLOTS` | int | 320 | Small-pool slots (range 1 512). Telemetry capacity is (slots - alarm reserved). At 1 packet/s, 320 slots with 32 reserved is about 288 seconds of backlog. Raise this only after a ram_report. Each slot costs the payload size plus about 32 bytes of metadata. |
| `CONFIG_SF_SMALL_PAYLOAD` | int | 64 | Small-pool payload capacity (bytes) (range 1 231) |
| `CONFIG_SF_SMALL_ALARM_SLOTS` | int | 32 | Small slots reserved for alarm (range 0 512). Telemetry cannot use these. Alarm can use any free slot. Must be <= CONFIG_SF_SMALL_SLOTS. |
| `CONFIG_SF_LARGE_SLOTS` | int | 0 | Large-pool slots (range 0 96). Leave at 0 until a test sends payloads above the small-pool size. Each slot is CONFIG_SF_LARGE_PAYLOAD bytes plus metadata. |
| `CONFIG_SF_LARGE_PAYLOAD` | int | 231 | Large-pool payload capacity (bytes) (range 1 231) |
| `CONFIG_SF_LARGE_ALARM_SLOTS` | int | 0 | Large slots reserved for alarm (range 0 96) |
| `CONFIG_SF_ACK_TIMEOUT_MS` | int | 200 | ACK wait after TX (ms) (range 1 5000). Provisional. A relay that is itself waiting for a downstream ACK can delay the upstream ACK by about this long. Measure RTT on a clean 1-hop run, then lower it with exp sett ack_timeout. Do not start from the spec's 40 ms until that capture exists. |
| `CONFIG_SF_MAX_ATTEMPTS` | int | 4 | Transmissions before the link is declared DOWN (range 1 8). Counts the first send. 4 means one send plus three retries. The packet stays in the store. |
| `CONFIG_SF_BACKOFF_MIN_MS` | int | 10 | Minimum retry backoff (ms) (range 0 1000) |
| `CONFIG_SF_BACKOFF_MAX_MS` | int | 20 | Maximum of the first retry window (ms) (range 0 5000) |
| `CONFIG_SF_BACKOFF_CAP_MS` | int | 80 | Backoff window cap (ms) (range 0 10000) |
| `CONFIG_SF_NACK_HOLDOFF_MS` | int | 1000 | Holdoff after QUEUE_FULL or NO_ROUTE (ms) (range 0 60000). Doubled when the ACK reports queue_free = 0. |
| `CONFIG_SF_INTER_TX_LISTEN_MS` | int | 20 | Listen gap after a completed exchange (ms) (range 0 1000) |
| `CONFIG_SF_RX_SLICE_MS` | int | 15 | Idle receive slice (ms) (range 1 500). An ACK is sent at the end of the slice that received the frame, so this is the worst-case extra ACK delay while idle. Stop also waits out the current slice. |
| `CONFIG_SF_HELLO_DEAD_MS` | int | 7000 | DOWN if a neighbour that has HELLO'd goes silent (ms, 0 = off) (range 0 600000). Applied only after at least one HELLO from that next hop. A peer with HELLO disabled does not kill the link. |
| `CONFIG_SF_T_PROBE_MS` | int | 3000 | Probe timer while DOWN (ms) (range 0 60000) |
| `CONFIG_SF_PROBE_FAST_MS` | int | 200 | Gap between successful probes (ms) (range 1 5000) |
| `CONFIG_SF_N_UP` | int | 3 | Consecutive probe replies required before UP (range 1 8) |
| `CONFIG_SF_HOLDDOWN_MIN_MS` | int | 5000 | First hold-down after UP to DOWN (ms) (range 0 60000) |
| `CONFIG_SF_HOLDDOWN_MAX_MS` | int | 60000 | Hold-down cap (ms) (range 0 120000) |
| `CONFIG_SF_HOLDDOWN_RESET_MS` | int | 60000 | Stable UP time that clears the hold-down streak (ms) (range 0 600000) |
| `CONFIG_SF_POLL_ALWAYS` |  | - | (selects another option) |
| `CONFIG_SF_CTRL_SUBSLOTS` | int | 8 | Default PHY length of HELLO, ACK and PROBE frames (subslots: 4, 8 or 16) (range 4 16). Runtime: exp sett ctrl_subslots 4/8/16. DATA frames use the length rule in sf_phy.h. |
| `CONFIG_SF_RSSI_LEVEL` | int | -60 | Default RX RSSI level passed to the modem (dBm) (range -127 0). Runtime: exp sett rssi_level <dBm>. |
| `CONFIG_SF_HOLD_CANCEL_MS` | int | 3000 | Silence after which a returning neighbour ends the hold-down (ms, 0 = off) (range 0 60000). A DOWN link whose neighbour was silent for at least this long and is then heard again goes to PROBING at once instead of waiting for the hold-down. Probing still needs N_UP replies. A neighbour that stays audible keeps the hold-down. Must be above the longest normal gap between frames from one node (a HELLO is every 1.8 to 2.2 s). Runtime: exp sett hold_cancel <ms>; 0 turns it off. |
| `CONFIG_SF_TELEMETRY_TTL_MS` | int | 600000 | Drop stored telemetry older than this (ms, 0 = never) (range 0 86400000) |
| `CONFIG_SF_STREAM_IDLE_MS` | int | 1800000 | Forget a dedup stream after this idle time (ms, 0 = never) (range 0 86400000) |
| `CONFIG_SF_ALARM_RATE` | int | 5 | Alarm token rate (per second) (range 0 100) |
| `CONFIG_SF_ALARM_BURST` | int | 10 | Alarm token burst (range 1 100) |
| `CONFIG_SF_ROUTE_MAX` | int | 4 | Route table entries (range 1 8) |
| `CONFIG_SF_LINK_MAX` | int | 4 | Next-hop link entries (range 1 8) |
| `CONFIG_SF_MAX_STREAMS` | int | 16 | Dedup streams (range 1 16) |
| `CONFIG_SF_NEIGH_MAX` | int | 8 | Neighbour table entries (range 1 8) |
| `CONFIG_SF_ACK_QUEUE` | int | 4 | ACKs that can be waiting to transmit (range 1 8) |
| `CONFIG_SF_RX_QUEUE` | int | 8 | Receive messages queued from the modem callback (range 2 16) |
| `CONFIG_SF_LOG_RX_CTRL` | bool | n | Log an RX line for every ACK, HELLO and PROBE. Off logs RX lines for DATA only. ACKs already appear as ACK_RX and ACK_TX and HELLO as TX, so the RX lines for control frames only add about 20% to the log volume, which matters at 115200 baud when the relay drains a backlog. On logs every control frame. |
| `CONFIG_SF_RX_EVENT_DRIVEN` | bool | y | Event-driven idle listening (one long receive instead of 15 ms slices). On: an idle node listens until its next deadline (generate, HELLO, link timers), at most SF_RX_MAX_MS, and the receive is ended early only when a frame arrives, a shell command needs the node, or the deadline is due (never in the middle of an arriving frame, and never during an ACK wait except by an ACK). Off: repeated slices of rx_slice ms. |
| `CONFIG_SF_RX_MAX_MS` | int | 1000 | Longest idle listen (ms) (range 20 5000). Upper bound on one idle receive operation. Also the worst-case lateness of a timer if a deadline is estimated too late. Must stay below SF_OP_TIMEOUT_MS. |
| `CONFIG_SF_CANCEL_ON_ACK` | bool | y | End the ACK wait as soon as an ACK frame is received. On: while a DATA or PROBE is in flight, the radio thread cancels the RX window when an ACK frame arrives, so the matching ACK is handled at once. Off: the RX window always runs for its full ack_timeout and received frames are handled only when it ends. Any ACK ends the wait early; the node then re-arms the remaining window, so an unrelated ACK costs one extra RX submit, not a lost ACK. |
| `CONFIG_SF_OP_TIMEOUT_MS` | int | 6000 | Give up on a modem TX/RX operation after (ms) (range 100 10000). The modem operation is then cancelled and the run stops. This is a hang guard, not the ACK timer. |
| `CONFIG_SF_RADIO_STACK` | int | 8192 | Radio thread stack (bytes). The radio thread builds a full frame (up to the PHY MTU) on the stack while another copy is waiting for the modem. 8192 covers that plus the log call. Lower it only after a stack report. |
| `CONFIG_SF_BOOT_LOOP_MAX` | int | 5 | Boots inside the guard window before radio start is delayed (range 1 20) |
| `CONFIG_SF_BOOT_DELAY_CAP_S` | int | 60 | Maximum boot-loop radio delay (seconds) (range 0 60) |
| `CONFIG_SF_BOOT_STABLE_S` | int | 300 | Continuous run that clears the boot-loop counter (seconds) (range 1 3600). There is no RTC, so "5 minutes of boots" is approximated by counting boots until the node has been running this long. |
| `CONFIG_SF_SHELL` | bool | y | exp shell |
| `CONFIG_SF_WAIT_FOR_START` | bool | y | Wait for exp start unless a profile enables autostart |
| `CONFIG_SF_PERSIST` | bool | y | Save profile and boot epoch in settings/NVS. exp save stores the profile. The boot epoch is a separate key and is not erased by exp factory. CONFIG_SETTINGS_NVS is a choice symbol; prj.conf sets it. |

An entry with default `-` has no default of its own: it is a member of a choice (role, overflow policy) or it is set by an overlay (for example the carrier by `overlay-us.conf`).
