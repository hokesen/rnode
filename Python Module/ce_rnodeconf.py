#!/usr/bin/env python3

import sys

import RNS.Utilities.rnodeconf as rnodeconf


def patch_ce_ids():
    # CE uses distinct Heltec V4 IDs to avoid colliding with Wireless Paper.
    rnodeconf.ROM.PRODUCT_H32_V4 = 0xC4
    rnodeconf.ROM.MODEL_CC = 0xCC
    rnodeconf.ROM.MODEL_CD = 0xCD

    rnodeconf.products[0xC4] = "Heltec LoRa32 v4 (CE)"
    rnodeconf.models[0xCC] = [
        470000000,
        510000000,
        22,
        "470 - 510 MHz",
        "rnode_firmware_heltec32v4.zip",
        "SX1262",
    ]
    rnodeconf.models[0xCD] = [
        863000000,
        928000000,
        22,
        "863 - 928 MHz",
        "rnode_firmware_heltec32v4.zip",
        "SX1262",
    ]


if __name__ == "__main__":
    patch_ce_ids()
    raise SystemExit(rnodeconf.main())
