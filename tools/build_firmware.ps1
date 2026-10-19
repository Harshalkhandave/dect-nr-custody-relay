<#
Build the firmware image at a short path, outside the repository and outside any synced folder.

  powershell -File tools\build_firmware.ps1                       # US overlay, cancel-on-ACK on
  powershell -File tools\build_firmware.ps1 -BuildDir C:\b\nocancel -Extra '-Dfirmware_CONFIG_SF_CANCEL_ON_ACK=n'
  powershell -File tools\build_firmware.ps1 -BuildDir C:\b\fast -Extra '-DEXTRA_DTC_OVERLAY_FILE=fast-uart.overlay'

Needs the NCS v3.2.1 toolchain bundle (nrfutil toolchain-manager install) at $Toolchain.
Output: <BuildDir>\merged.hex (flash this) and <BuildDir>\firmware\zephyr\.config.
Check .config for the options you meant to set; a mistyped -D option is silently ignored.
#>
param(
	[string]$BuildDir = 'C:\b\custody',
	[string]$Extra = '',
	[string]$Toolchain = 'C:\ncs\toolchains\66cdf9b75e',
	[string]$Ncs = 'C:\nordic\ncs\v3.2.1'
)
$T = $Toolchain
$env:PATH = "$T;$T\mingw64\bin;$T\bin;$T\opt\bin;$T\opt\bin\Scripts;$T\opt\nanopb\generator-bin;$T\nrfutil\bin;$T\opt\zephyr-sdk\arm-zephyr-eabi\bin;$env:PATH"
$env:PYTHONPATH = "$T\opt\bin;$T\opt\bin\Lib;$T\opt\bin\Lib\site-packages"
$env:ZEPHYR_TOOLCHAIN_VARIANT = 'zephyr'
$env:ZEPHYR_SDK_INSTALL_DIR = "$T\opt\zephyr-sdk"
$env:ZEPHYR_BASE = "$Ncs\zephyr"
$src = Join-Path (Split-Path $PSScriptRoot -Parent) 'firmware'
Set-Location $Ncs
$westArgs = @('build', '-b', 'conexio_stratus_pro/nrf9151/ns', '--sysbuild', '-d', $BuildDir, $src, '--',
	"-DBOARD_ROOT=$($Ncs.Replace('\','/'))/conexio-firmware-sdk", '-DEXTRA_CONF_FILE=overlay-us.conf')
if ($Extra) { $westArgs += $Extra }
west @westArgs
exit $LASTEXITCODE
