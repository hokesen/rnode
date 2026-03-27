# Precompiled Firmware
The firmware is now handled and installed to RNodes directly through `rnodeconf`, which is inclueded in the `rns` package. It can be installed via `pip`:

```
# Install rnodeconf via rns package
pip install rns --upgrade

# Install the firmware on a board with the install guide
rnodeconf --autoinstall
```

This fork also includes Heltec LoRa32 v4 support. The corresponding build target is `heltec32_v4`, and release builds produce `Release/rnode_firmware_heltec32v4.zip`. For board-specific build and install notes, see [`Documentation/BUILDING.md`](../Documentation/BUILDING.md).
