# Overlays and configuration files

Besides the source code and `Kconfig` (see [`KCONFIG_REFERENCE.md`](KCONFIG_REFERENCE.md)), a few small files decide how the firmware is built.

| File | What it contains |
|---|---|
| `prj.conf` | the project settings, explained below |
| `overlay-us.conf` | `CONFIG_CARRIER=1711` and `CONFIG_TX_POWER=10` (US 1.9 GHz DECT band) |
| `overlay-eu.conf` | `CONFIG_CARRIER=1677` |
| `sysbuild.conf` | `SB_CONFIG_BOOTLOADER_MCUBOOT=y`, which builds the MCUboot bootloader together with the app |
| `fast-uart.overlay` | an optional device-tree overlay that sets the console UART to 460800 baud instead of 115200. It has not been tested on the Stratus Pro USB-serial bridge |
| `CMakeLists.txt` | the list of source files and the revision shown at boot |

## Choosing a carrier

Add one overlay to the build with `-DEXTRA_CONF_FILE=overlay-us.conf` or `-DEXTRA_CONF_FILE=overlay-eu.conf`. Without one the carrier stays 0 and the radio does not start. The carrier is a regulatory choice, so check the rules of your region first.

To use the fast UART, also add `-DEXTRA_DTC_OVERLAY_FILE=fast-uart.overlay` and start the serial logger with `--baud 460800`.

## What `prj.conf` sets

| Setting | Why |
|---|---|
| `CONFIG_NRF_MODEM_LIB`, `CONFIG_NRF_MODEM_LINK_BINARY_DECT_PHY` | use the modem library with the DECT PHY-only link binary (the `nrf_modem_dect_phy_*` API, no MAC) |
| `CONFIG_MODEM_ANTENNA=n`, `CONFIG_HWINFO=y` | no antenna driver; the node id comes from the chip |
| `CONFIG_LOG`, `CONFIG_LOG_MODE_DEFERRED`, `CONFIG_LOG_BUFFER_SIZE=32768`, `CONFIG_SF_LOG_LEVEL_INF` | the protocol lines are logged at level INF into a 32 KB deferred buffer |
| `CONFIG_LOG_PROCESS_THREAD_SLEEP_MS=50` | the log thread wakes every 50 ms, so the host's time stamps stay close to the board clock |
| `CONFIG_BOOTLOADER_MCUBOOT=y` | build a signed image for MCUboot |
| `CONFIG_SF_SHELL`, `CONFIG_SF_WAIT_FOR_START`, `CONFIG_SF_PERSIST` | the `exp` shell, wait for `exp start` after boot, keep a settings profile in flash |
| `CONFIG_SHELL_STACK_SIZE=3072`, `CONFIG_SHELL_CMD_BUFF_SIZE=256` | shell sizes |
| `CONFIG_FLASH`, `CONFIG_FLASH_MAP`, `CONFIG_FLASH_PAGE_LAYOUT`, `CONFIG_MPU_ALLOW_FLASH_WRITE`, `CONFIG_NVS`, `CONFIG_SETTINGS`, `CONFIG_SETTINGS_NVS` | storage for the settings profile and the boot counter |
| `CONFIG_PM_PARTITION_SIZE_SETTINGS_STORAGE=0x4000` | size of the settings partition |
| `CONFIG_SF_BOOT_DELAY_CAP_S=0` | no radio delay after repeated quick reboots. In the measurements every node is rebooted before each run, and that delay would hold the radio for 2 to 60 s |
| `CONFIG_MAIN_STACK_SIZE=2048` | the main thread writes the settings flash at boot, and with the default 1024 bytes the stack overflowed on a boot that rotates flash sectors |

## The revision printed at boot

When CMake configures the build, it asks git for the revision of the `firmware/` sources and passes it to the code as `SF_GIT_REV`. The `BOOT_INFO` line prints it as `fw=`. A `-dirty` suffix means uncommitted changes, and `unknown` means the build was not made inside a git checkout. Use a fresh build directory after a commit so the revision is read again. The recorded runs show `fw=b872b79f`.
