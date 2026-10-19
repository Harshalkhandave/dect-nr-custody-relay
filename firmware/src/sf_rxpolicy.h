/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Pure decision for the idle receive. No Zephyr and no modem: compiled by the image and by the host test.
 */

#ifndef SF_RXPOLICY_H_
#define SF_RXPOLICY_H_

#include <stdbool.h>
#include <stdint.h>

enum sf_rx_event {
	SF_RXE_FRAME,    /* a frame was received and queued */
	SF_RXE_ACK,      /* an ACK frame was received and queued */
	SF_RXE_WAKE,     /* a shell command changed something (start, stop, setting) */
	SF_RXE_DEADLINE, /* the node's next deadline is reached */
};

enum sf_rx_action {
	SF_RXA_CONTINUE,       /* keep listening, ignore the event */
	SF_RXA_CANCEL_NOW,     /* cancel the receive and let the node act */
	SF_RXA_WAIT_FRAME_END, /* a frame is arriving: wait for its end, then cancel */
};

struct sf_rx_state {
	bool ack_wait;           /* a DATA or PROBE of ours waits for its ACK */
	bool frame_in_progress;  /* a frame start was seen, its end not yet */
};

static inline enum sf_rx_action sf_rx_decide(const struct sf_rx_state *s, enum sf_rx_event e)
{
	switch (e) {
	case SF_RXE_ACK:
		/* the one event allowed to end an ACK wait. */
		return SF_RXA_CANCEL_NOW;
	case SF_RXE_FRAME:
		/* during an ACK wait other frames stay queued until the wait ends.
		 * when idle, a complete frame is handed to the node at once.
		 */
		return s->ack_wait ? SF_RXA_CONTINUE : SF_RXA_CANCEL_NOW;
	case SF_RXE_WAKE:
	case SF_RXE_DEADLINE:
	default:
		/* never cut a frame that is arriving. */
		return s->frame_in_progress ? SF_RXA_WAIT_FRAME_END : SF_RXA_CANCEL_NOW;
	}
}

#endif /* SF_RXPOLICY_H_ */
