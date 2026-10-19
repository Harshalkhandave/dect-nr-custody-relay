/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Type-1 PHY header packet_length code for a frame. No Zephyr and no modem:
 * compiled by the image and by the host test.
 */

#ifndef SF_PHY_H_
#define SF_PHY_H_

#include "sf_types.h"

#include <stdint.h>

/*
 * DATA uses this rule (up to 32 bytes: 0x03, up to 64: 0x07, else 0x0F).
 * HELLO, ACK and PROBE use at least the length chosen by ctrl_subslots (4, 8 or 16 subslots
 * = 0x03, 0x07, 0x0F), never less than the rule above, so ctrl_subslots 4 gives the 4-subslot code for control frames.
 */
static inline uint8_t sf_phy_len_code(uint8_t frame_type, uint16_t len, uint8_t ctrl_subslots)
{
	uint8_t code = len <= 32 ? 0x03 : (len <= 64 ? 0x07 : 0x0F);
	uint8_t ctrl = ctrl_subslots >= 16 ? 0x0F : (ctrl_subslots >= 8 ? 0x07 : 0x03);

	if (frame_type != SF_TYPE_DATA && ctrl > code) {
		code = ctrl;
	}
	return code;
}

#endif /* SF_PHY_H_ */
