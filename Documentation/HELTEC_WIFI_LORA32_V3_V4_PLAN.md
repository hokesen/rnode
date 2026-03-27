# Heltec WiFi LoRa 32 V3/V4 Investigation and CE Support Plan

## Scope
This note captures:

- The current state of Heltec support in this CE checkout
- The official Heltec V3.2 and V4.x hardware differences relevant to RNode
- The deprecated parent repository's prior V4 work
- A recommended plan for bringing Heltec V4 support into this CE fork safely

Official vendor source files downloaded for this comparison are stored under:

- `Documentation/vendor/heltec_wifi_lora_32/v3/`
- `Documentation/vendor/heltec_wifi_lora_32/v4/`

The downloaded set includes:

- V3.2 datasheet PDF
- V3.2 schematic PDF
- V3.2 pinmap PNG
- V3 hardware update log HTML
- V3 GPIO usage guide HTML
- V4.2 datasheet PDF
- V4.2 schematic PDF
- V4.3 schematic PDF
- V4 pinmap PNG
- V4 hardware update log HTML
- V4 FAQ HTML

## Current CE State
The current CE checkout supports Heltec V3, but not a distinct Heltec V4 target.

Observed locally:

- `README.md` and `Documentation/BUILDING.md` list Heltec LoRa32 v3, but not v4.
- `Makefile` has `firmware-heltec32_v3`, but no `firmware-heltec32_v4`.
- `Boards.h` contains a full `BOARD_HELTEC32_V3` definition.
- `Power.h` contains Heltec V3 battery measurement support using `pin_vbat = 1` and `pin_ctrl = 37`.
- `Display.h`/`Boards.h` assumptions for V3 match the V3.2 schematic well enough for the existing target.

Important CE-specific constraint:

- `Boards.h` already uses `PRODUCT_H_W_PAPER = 0xC3`, `BOARD_H_W_PAPER = 0x3F`, and `MODEL_C8`.
- The parent repo reused those same numeric IDs for Heltec V4.
- That means the parent repo's V4 ID assignments cannot be cherry-picked directly into this CE tree without colliding with CE's existing Wireless Paper identifiers.

## Parent Repository Prior Art
The deprecated parent repository at `markqvist/RNode_Firmware` does contain Heltec V4 work on `upstream/master`.

Relevant observations from the parent repo:

- It adds `PRODUCT_H32_V4 = 0xC3`, `BOARD_HELTEC32_V4 = 0x3F`, and `MODEL_C8`.
- It adds a `firmware-heltec32_v4` build target.
- That build target uses generic `esp32:esp32:esp32s3:CDCOnBoot=cdc`, not `heltec_wifi_lora_32_V3`.
- It adds explicit V4 PA/LNA control assumptions and allows TX power above the stock SX1262 22 dBm limit.
- It also skips the `while (!Serial)` wait for the V4 target, consistent with native-USB style bring-up.

This is useful prior art, but it is not drop-in compatible with CE because:

- The CE fork already uses the parent's proposed V4 numeric IDs for Wireless Paper.
- CE has a different and newer multi-interface radio abstraction than the parent repo.
- The parent repo's hard-coded V4 PA pin assumptions appear to target an earlier V4 board revision than the latest official V4.3.x documentation.

## Hardware Comparison
## V3.2 baseline
Official Heltec V3.2 documentation shows:

- ESP32-S3 MCU
- SX1262 LoRa transceiver
- OLED on `GPIO17`/`GPIO18` with reset on `GPIO21`
- LoRa bus on `GPIO8`/`9`/`10`/`11`/`12`/`13`/`14`
- Battery sense on `GPIO1`
- `ADC_Ctrl` on `GPIO37`
- `Vext_Ctrl` on `GPIO36`
- LED activity on `GPIO35`

The V3.2 hardware update log explicitly notes that the voltage detection circuit changed and now requires pulling up `ADC_Ctrl (GPIO37)`. The existing CE V3 PMU code already does this, which is a good sign that the current V3 support matches the late V3 hardware revision.

## V4.0/V4.2 common changes
Official Heltec V4 documentation shows the following board-level changes relative to V3:

- ESP32-S3R2 instead of the V3's ESP32-S3N8/S3FN8 packaging
- 16 MB external flash plus 2 MB PSRAM
- LoRa output increased from `21 +/- 1 dBm` to `28 +/- 1 dBm`
- CP2102 removed
- Added GNSS connector and related control pins
- Added solar input
- Increased header exposure from 36 pins to 40 pins
- OLED moved to a B2B-connected removable assembly
- FAQ states V3 and V4 are compatible in most scenarios, but TX power settings may no longer map directly to actual RF output

The V4.2 schematic and pinmap still show the core V3-compatible signals in familiar places:

- LoRa pins remain `GPIO8` through `GPIO14`
- OLED still uses `GPIO17`, `GPIO18`, and `GPIO21`
- `ADC_Ctrl` remains on `GPIO37`
- `Vext_Ctrl` remains on `GPIO36`
- LED remains on `GPIO35`

That strongly suggests a conservative "V3-compatible V4 bring-up" is viable.

## V4.3.x complication
The latest official V4 FAQ says "Hardware version 4.3 requires new firmware".

The official V4.3.1 hardware notes add one especially important warning:

- FEM control changed to `GPIO5`
- `GPIO46` is now available as a user pin

However:

- The V4.2 pinmap and V4.3 schematic text still expose `VFEM_Ctrl 7`
- The parent repo's V4 support hard-codes PA control around `GPIO7`, `GPIO2`, and `GPIO46`

That mismatch means CE should not assume one V4 hardware revision. At minimum, the firmware plan should expect a split between early V4 boards and V4.3.x boards.

## Implications for RNode CE
## What looks reusable from V3
The following V3 behavior likely carries over directly to an initial V4 target:

- SX1262 modem selection
- LoRa SPI pin mapping
- OLED pin mapping
- Battery sense on `GPIO1`
- `ADC_Ctrl` usage on `GPIO37`
- `Vext_Ctrl` usage on `GPIO36`
- Button on `GPIO0`
- LED on `GPIO35`
- Sleep/wake model based on `GPIO0`

## What does not carry over cleanly
V4 needs additional handling beyond a pure V3 alias because:

- It no longer wants the Heltec V3 board profile for builds and uploads
- It removes CP2102, so native USB/CDC behavior matters
- It supports higher RF output than a plain SX1262 front-end
- It likely needs external FEM/LNA control
- Official docs indicate a hardware-revision split inside the V4 family

## CE-specific blockers
Bringing V4 into CE is not just adding another board table entry.

The main blockers are:

- Numeric ID collision with CE's existing Wireless Paper product/model assignments
- No CE-side notion of a Heltec V4 product in EEPROM validation or product tables
- No CE-side build target or release target for `heltec32_v4`
- No CE-side explicit external PA/LNA abstraction for SX1262-based Heltec boards
- No CE-side documented distinction between V4.0/V4.2 and V4.3.x hardware

## Recommended Plan
## Phase 1: Conservative V4 bring-up
Goal: land a safe V4 target that boots, uploads, displays, measures battery, and does basic LoRa RX/TX without depending on unverified 28 dBm FEM behavior.

Steps:

- Add a new CE-specific Heltec V4 product/board/model assignment that does not reuse `0xC3`, `0x3F`, or `MODEL_C8` while Wireless Paper still owns them in CE.
- Add `heltec32_v4` build and release targets to `Makefile`.
- Use generic `esp32:esp32:esp32s3:CDCOnBoot=cdc` for build/upload, following the parent repo.
- Add a new board definition that starts from the V3.2 pin map:
  - LoRa `8/9/10/11/12/13/14`
  - OLED `17/18/21`
  - battery sense `1`
  - `ADC_Ctrl 37`
  - `Vext_Ctrl 36`
  - LED `35`
  - button `0`
- Reuse the V3 battery measurement formula initially, but validate on real hardware before finalizing.
- Skip `while (!Serial)` for V4, like the parent repo.
- Add product/model validation and documentation updates in:
  - `README.md`
  - `Documentation/BUILDING.md`
  - any EEPROM/product lookup tables

Acceptance criteria:

- `make firmware-heltec32_v4` succeeds
- basic serial boot works on native USB
- OLED initializes
- battery voltage reads sensibly
- RX/TX works at conservative power settings up to 21 or 22 dBm

## Phase 2: Add explicit V4 FEM/LNA support
Goal: support the V4's higher-power front-end without destabilizing earlier boards.

Steps:

- Introduce CE-side board capabilities for external PA/LNA/FEM control rather than hard-coding V4 assumptions into the generic SX1262 path.
- Add per-board or per-variant metadata for:
  - maximum allowed TX power
  - optional FEM enable pin
  - optional PA control pins
  - optional LNA gain compensation
  - optional sleep/shutdown handling for the RF front-end
- Extend CE's TX power handling so a V4 target can advertise and enforce a higher ceiling than stock SX1262 boards.
- Review CE's interference and RSSI/noise-floor logic for any gain-offset correction needed when the external LNA path is active.

Acceptance criteria:

- TX power control is no longer capped as if the board were a plain SX1262 module
- sleep/wake correctly powers down the external front-end
- RSSI/interference behavior is stable under both idle and active traffic

## Phase 3: Split hardware revisions if needed
Goal: handle the V4.3.x pin change without breaking earlier V4 boards.

Recommended approach:

- Introduce a CE board variant for early V4 hardware and a separate CE board variant for V4.3.x
- Keep the same user-facing board family name, but select the hardware revision with `BOARD_VARIANT` or a similar CE-native mechanism
- Do not assume the parent repo's PA pin mapping is correct for V4.3.x without bench validation

Why this matters:

- The official docs indicate at least one control-pin change inside the V4 family
- A single hard-coded PA/LNA mapping risks silent RF failure or unstable power behavior

## Suggested Work Order
If implementation begins immediately, the highest-leverage order is:

1. Add a non-conflicting CE board ID/product/model strategy for Heltec V4
2. Add a compile-only `heltec32_v4` target using generic `esp32s3:CDCOnBoot=cdc`
3. Port the V3-like board mapping and PMU/display setup
4. Verify basic RX/TX at conservative power levels
5. Add CE-native FEM/LNA capability flags and TX power extensions
6. Split V4.0/V4.2 from V4.3.x if bench tests confirm the doc-level pin mismatch is real
7. Update user-facing support lists and flashing/build docs

## Current Implementation Status
As of March 26, 2026, the CE fork now has an initial Heltec V4 bring-up target implemented locally.

Implemented so far:

- `BOARD_HELTEC32_V4` has been added with CE-local product/board/model IDs that do not collide with Wireless Paper.
- `firmware-heltec32_v4`, `upload-heltec32_v4`, and `release-heltec32_v4` targets have been added to `Makefile`.
- The V4 target currently builds against generic `esp32:esp32:esp32s3:CDCOnBoot=cdc`.
- Display, battery measurement, native USB serial startup, and LED handling currently follow the V3-compatible pin mapping.
- The Arduino CLI toolchain has been configured to use repo-local state under `./.arduino15`, `./.arduino`, and `./.arduino-cache`.

Validation completed in this environment:

- `make firmware-heltec32_v4` succeeds.
- `make release-heltec32_v4` succeeds.
- The packaged release artifact is generated at `Release/rnode_firmware_heltec32v4.zip`.

Not implemented yet:

- Verified V4 external PA/LNA/FEM support
- Any V4.3.x-specific control-pin split
- Bench validation of battery scaling and RF power behaviour on real hardware

## Real Board Validation Plan
When testing on a physical Heltec V4 board, validate in this order:

1. Flash the generated V4 image over native USB and confirm the board enumerates on a CDC/ACM serial port.
2. Confirm the board boots without stalling on `while (!Serial)` and emits the normal startup logs.
3. Confirm the OLED powers on and renders the expected boot/display output.
4. Confirm the onboard LED activity still behaves sensibly during boot and packet activity.
5. Confirm battery telemetry is plausible when powered from USB and when powered from battery.
6. Perform low-power RX/TX checks first at conservative output power.
7. Only after stable baseline RX/TX is confirmed, test higher TX power behaviour and inspect whether a FEM control path is required.
8. If the board is a V4.3.x unit, compare observed RF behaviour against the documented `GPIO5` FEM-control change before enabling any higher-power path in CE.

Suggested first bench commands:

- `make firmware-heltec32_v4`
- `make release-heltec32_v4`
- `make upload-heltec32_v4 port=<your-serial-device>`

If first hardware tests show that RF works only at low power or fails entirely above conservative settings, treat that as evidence that Phase 2 or Phase 3 is required rather than as proof that the basic V4 bring-up is wrong.

## Bottom Line
Heltec V4 support is feasible in CE, but it should not be treated as a trivial alias of Heltec V3 and it should not be ported blindly from the deprecated parent repo.

The safest path is:

- Reuse V3-compatible board mapping for first bring-up
- Use the parent repo only as design input, not as a direct patch source
- Preserve CE compatibility by avoiding the parent repo's conflicting numeric IDs
- Treat V4.3.x as a likely separate board variant until the FEM control pin mapping is verified on hardware
