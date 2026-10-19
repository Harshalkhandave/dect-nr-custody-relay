# Shell commands

You control the firmware through one shell command, `exp`, on the console (115200 baud, 8N1, over the board's USB serial port). After boot the node is idle until you type `exp start`, unless a saved profile turns on autostart.

A typical session on a source node looks like this:

```
exp role source
exp sett dest <sink id>
exp route set <sink id> <relay id>
exp sett size 16
exp start 180
exp status
exp stop
```

## All commands

| Command | What it does |
|---|---|
| `exp status` | shows the role, the counters (generated, delivered, stored, drained, retries and more) and the frame that is waiting for an ACK |
| `exp sf` | shows how full the store is |
| `exp link` | shows the state of each next-hop link (DOWN, PROBING or UP) |
| `exp neigh` | lists the neighbours the node has heard |
| `exp route` | lists the routes. `exp route set <dst> <next>` adds one and `exp route del <dst>` removes one |
| `exp role source\|relay\|sink` | sets the role. Changing the role drops all stored frames |
| `exp start [count]` | starts the node. `count` is how many frames a source creates in this run. Without it the `count` setting is used. Starting empties the store, clears the counters and, with `liveness any`, resets the links |
| `exp stop` | stops the node and prints a `SUMMARY` line. A stopped node neither receives nor sends |
| `exp sett` | lists all settings. `exp sett <key> <value>` changes one (see [`SETTINGS_REFERENCE.md`](SETTINGS_REFERENCE.md)) |
| `exp flush` | drops every stored frame |
| `exp alarm` | queues one alarm frame on a running source (limited by a token rate) |
| `exp save` | writes the settings to flash. The stored frames are never saved |
| `exp load` | loads the saved settings |
| `exp factory` | erases the saved settings. The boot counter stays |
| `exp autostart [on\|off]` | shows or sets whether the node starts by itself after boot (needs `exp save`) |
| `exp reboot` | reboots the board. Links, duplicate memory, store and counters start from zero |

A few settings (`ctrl_subslots`, `rx_mode` and `liveness`) cannot be changed while the node is running. Stop it first.

The shell is only built in when `CONFIG_SF_SHELL=y`, which is the default.
