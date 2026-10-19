# Custody firmware

This is the firmware that runs on the source, relay and sink boards. It targets the Conexio Stratus Pro (Nordic nRF9151) and is built with Zephyr and the nRF Connect SDK. It talks to the radio only through the modem's DECT NR+ PHY API (`nrf_modem_dect_phy_*`), so there is no MAC layer underneath.

One image runs on every board. After boot you choose the role (source, relay or sink) and all settings with the `exp` shell commands.

## What it does

- **Store.** Every node keeps frames in a RAM store (320 slots, 32 of them reserved for alarms) until the next hop has taken them over.
- **Custody.** A node sends one frame at a time and waits for an ACK from the next hop. Without an ACK it retries with a short random wait, up to four sends in total. Once the ACK arrives, the node frees the slot. The receiver ignores duplicates by remembering the highest sequence number it has seen from each source.
- **Link state.** For each next hop the node tracks DOWN, PROBING or UP. After four failed sends, or after a long silence, the link goes DOWN. A waiting time and a few probe frames bring it back. While the link is not UP, new frames stay in the store.
- **Open-loop mode.** With `exp sett custody off` the same image sends every frame once, without ACK, retry or link state. This is the baseline used in the paper.

## Quick facts

| | |
|---|---|
| Board target | `conexio_stratus_pro/nrf9151/ns`, built with sysbuild and MCUboot |
| SDK | nRF Connect SDK v3.2.1 (Zephyr 4.2.99) |
| Overlay | `overlay-us.conf` or `overlay-eu.conf` (one of them is required, otherwise the carrier is 0) |
| Console | 115200 baud, 8N1, shell command `exp` |
| Modem firmware | DECT NR+ modem firmware (the measurements used `mfw-nr+_nrf91x1_1.1.0`) |

On this modem use `exp sett size 16`. Payloads of 48 and 64 bytes are padded by the PHY slot and rejected.

## Documentation

The documents are in [`docs/`](docs/).

| Read this | To learn |
|---|---|
| [`BUILD_AND_FLASH.md`](docs/BUILD_AND_FLASH.md) | how to build and flash (this follows Conexio's documentation) |
| [`OVERLAYS.md`](docs/OVERLAYS.md) | what `prj.conf`, the overlays and `sysbuild.conf` set |
| [`KCONFIG_REFERENCE.md`](docs/KCONFIG_REFERENCE.md) | every build option with its default |
| [`SHELL_COMMANDS.md`](docs/SHELL_COMMANDS.md) | the `exp` commands |
| [`SETTINGS_REFERENCE.md`](docs/SETTINGS_REFERENCE.md) | every `exp sett` setting |
| [`WIRE_FORMAT.md`](docs/WIRE_FORMAT.md) | what a frame looks like on the air |
| [`LINK_STATE.md`](docs/LINK_STATE.md) | how the link states change |
| [`LOG_REFERENCE.md`](docs/LOG_REFERENCE.md) | what each log line means |
| [`ARCHITECTURE_GUIDE.md`](docs/ARCHITECTURE_GUIDE.md) | how the code is organized and how a frame travels through it |
| [`MODEM_AND_BOARD_INFO.md`](docs/MODEM_AND_BOARD_INFO.md) | modem firmware, supported bands and the boot lines |
| [`LIMITATIONS.md`](docs/LIMITATIONS.md) | what the firmware does not do |
| [`TESTING.md`](docs/TESTING.md) | the tests that run on a PC |

## Source files (`src/`)

| File | What it does |
|---|---|
| `sf_node.c` | all protocol decisions: custody, retries, how the link state is used, duplicates, settings. It does not touch hardware |
| `sf_codec.c` | turns frames into bytes and back |
| `sf_dedup.c` | duplicate detection |
| `sf_store.c` | the RAM store |
| `sf_link.c` | link states, hold-down and probe timers |
| `sf_rxpolicy.h`, `sf_phy.h`, `sf_types.h` | when to end a receive, the PHY length rule, shared types |
| `sf_port.c` | connects the node logic to Zephyr: defaults, locking, the receive queue |
| `main.c` | modem start-up, the radio thread and the modem callbacks |
| `sf_shell.c` | the `exp` shell |
| `sf_persist.c` | saved settings and the boot counter in flash |

How the firmware was used in the measurements is described in [`../docs/RUNNING_THE_EXPERIMENT.md`](../docs/RUNNING_THE_EXPERIMENT.md).
