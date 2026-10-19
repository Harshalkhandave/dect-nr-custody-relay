# Modem and board information

This page collects what is known about the nRF9151 modem on the Stratus Pro boards used for the measurements. The values were read from one board with Nordic's `dect_shell` sample (nRF Connect SDK v3.2.1) using the commands `version`, `kernel version`, `dect status` and `at <AT command>`. Nothing was written to the modem.

## What the board reported

| Item | Value | How it was read |
|---|---|---|
| Modem firmware | `mfw-nr+_nrf91x1_1.1.0` (DECT NR+ modem firmware for the nRF91x1 family, release 1.1.0) | `at AT+CGMR`, `dect status` |
| Chip | `nRF9151 LACA A1A` (package LACA, revision A1A) | `at AT%HWVERSION` |
| Modem firmware UUID | `8d869cd6-361c-49ac-b993-b32dad1da137` | `at AT%XMODEMUUID` |
| Zephyr | 4.2.99 | `kernel version` |

The same modem version, hardware and UUID are printed by the firmware itself at every boot (see below), so you can check your own boards without `dect_shell`.

## DECT bands reported by the modem (`dect status`)

| Band | Carriers | Power class | Max power | RX gain |
|---|---|---|---|---|
| 1 | 1657 to 1677 | 2 | 21 dBm | -4 |
| 2 | 1680 to 1700 | 2 | 21 dBm | -4 |
| 4 (band group 1) | 524 to 552 | 3 | 19 dBm | -4 |
| 9 | 1703 to 1711 | 2 | 21 dBm | -4 |
| 22 | 1691 to 1711 | 2 | 21 dBm | -4 |

Carrier 1711 (`overlay-us.conf`) is the highest carrier of both band 9 and band 22. Carrier 1677 (`overlay-eu.conf`) is the highest carrier of band 1. The modem reports a maximum output of 21 dBm for power class 2. That is a ceiling for the radio, not the output of any TX power index. The firmware's index (0 to 13) has no known mapping to dBm, so this repository never states a power in dBm.

## Queries that the modem answers with an error

`AT+CGMI` (manufacturer), `AT+CGMM` (model), `AT+CGSN=1` (IMEI), `AT%SHORTSWVER`, `AT+CFUN?` and `AT+CGDCONT?`. These are not available on this modem firmware, or they make no sense in a PHY-only DECT mode. As a result there is no IMEI to read in this state. The node id used by the firmware comes from the chip's own unique id, read with `hwinfo_get_device_id`.

## What the firmware prints at boot

At every boot the firmware prints two lines:

```
BOOT_INFO: fw=b872b79f ncs=3.2.1 zephyr=4.2.99 main_stack=2048 radio_stack=8192 carrier=1711 net=91
BOOT_MODEM: fw=mfw-nr+_nrf91x1_1.1.0 hw=nRF9151 LACA A1A uuid=8d869cd6-361c-49ac-b993-b32dad1da137 temp_c=25 vbat_mv=5058
```

`BOOT_INFO` shows the firmware revision, SDK and Zephyr versions, the two stack sizes, the carrier and the network id. `BOOT_MODEM` shows the modem firmware version, the hardware, the UUID, the modem temperature and the supply voltage. The run harness copies both lines for every board into the `boot_info` field of each run's `manifest.json`, so every run records which modem firmware it used.
