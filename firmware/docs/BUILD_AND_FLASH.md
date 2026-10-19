# Build and flash

Building and flashing work the way Conexio describes for the Stratus Pro. This page does not repeat their steps. It tells you which of Conexio's pages to follow and which values to use for this firmware. There are no prebuilt images, so you build from source.

## Follow Conexio's documentation

1. [Fetch Conexio Firmware SDK and Board Definition Files](https://docs.conexiotech.com/master/building-and-programming-an-application/fetch-conexio-firmware-sdk-and-board-definition-files). This gets the `conexio-firmware-sdk` folder, which contains the Stratus Pro board definition.
2. [Building and Programming an Application using CLI and west](https://docs.conexiotech.com/master/building-and-programming-an-application/building-and-programming-an-application-using-cli-and-west). This shows how to build and how to put an image on the board (USB DFU mode and `newtmgr`).
3. [Conexio Stratus Board Definition Files](https://docs.conexiotech.com/master/building-and-programming-an-application/conexio-stratus-board-definition-files). This describes the board files and the MCUboot configuration.
4. [Conexio firmware SDK on GitHub](https://github.com/Conexiotechnologies/conexio-firmware-sdk), for the board files that match the current nRF Connect SDK.

Conexio's pages use other SDK versions and the nRF9161 in their examples. For this firmware use the values below.

## Values for this firmware

| Item | Value |
|---|---|
| nRF Connect SDK | v3.2.1 (Zephyr 4.2.99) |
| Board target | `conexio_stratus_pro/nrf9151/ns` |
| Build type | sysbuild, with the MCUboot bootloader |
| Board root | `-DBOARD_ROOT=<NCS>/conexio-firmware-sdk` |
| Carrier overlay | `-DEXTRA_CONF_FILE=overlay-us.conf` (carrier 1711) or `overlay-eu.conf` (carrier 1677) |
| Source folder | `firmware/` of this repository |

You always need one of the two overlays. Without it the carrier is 0 and the radio does not start. See [`OVERLAYS.md`](OVERLAYS.md).

On Windows, `tools/build_firmware.ps1` shows the complete command (it sets the toolchain paths and runs `west build -b conexio_stratus_pro/nrf9151/ns --sysbuild -d <BuildDir> firmware -- -DBOARD_ROOT=... -DEXTRA_CONF_FILE=overlay-us.conf`). Build in a folder outside the repository, at a short path. Long folder names break nRF Connect SDK builds on Windows.

## Flash

Use the method on Conexio's "Building and Programming" page: USB DFU mode with the signed image `app_update.bin`, or `west flash` with a debug probe.

## Modem firmware

The DECT NR+ PHY API needs the DECT NR+ modem firmware on the board. The boards used for the measurements ran `mfw-nr+_nrf91x1_1.1.0`. It is not part of this repository. Conexio's [modem firmware page](https://docs.conexiotech.com/master/mfw) describes how to update the LTE modem firmware over SWD and asks you to contact Conexio first. For the NR+ modem firmware, ask Nordic or Conexio. At every boot the firmware prints the modem version (`BOOT_MODEM`).

## After flashing

- Open the serial console at 115200 baud, 8N1.
- The node waits for `exp start`. `exp status` shows its node id and role, and `exp sett` lists all settings.
- Each board takes its node id from its own chip, so your ids will differ from the ones in the recorded data.
- The commands used in the measurements are in [`../../docs/RUNNING_THE_EXPERIMENT.md`](../../docs/RUNNING_THE_EXPERIMENT.md). All commands are in [`SHELL_COMMANDS.md`](SHELL_COMMANDS.md).

## A note on regulations

The US overlay uses carrier 1711 in the 1.9 GHz DECT band. Check the rules of your region before you transmit. This project does not claim regulatory compliance. The listen-before-talk threshold is set to 0 dBm, which means the radio never waits for a busy channel (see [`LIMITATIONS.md`](LIMITATIONS.md)).
