/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef SF_LINK_H_
#define SF_LINK_H_

#include "sf_types.h"

struct sf_link {
	bool used;
	uint16_t next_id;
	uint8_t state;
	uint8_t consec;
	uint8_t down_streak;
	bool heard; /* a frame (any type, with CONFIG_SF_LIVENESS_ANY_FRAME) was heard from next_id */
	int64_t last_heard_ms;
	bool returned; /* silent neighbour came back: leave DOWN without waiting for the hold-down */
	int64_t hold_until_ms;
	int64_t up_since_ms;
	int64_t next_probe_ms;
};

struct sf_link_table {
	struct sf_link item[SF_LINK_CAP];
};

typedef void (*sf_link_fn)(void *ctx, const struct sf_link *link, uint8_t old_state,
			   const char *reason);

void sf_link_init(struct sf_link_table *t);
struct sf_link *sf_link_find(struct sf_link_table *t, uint16_t next_id);
struct sf_link *sf_link_ensure(struct sf_link_table *t, uint16_t next_id, int64_t now,
			       bool assume_up);
void sf_link_tick(struct sf_link_table *t, int64_t now, uint32_t hello_dead_ms, uint32_t t_probe_ms,
		  uint32_t hold_min_ms, uint32_t hold_max_ms, uint32_t hold_reset_ms,
		  sf_link_fn on_change, void *ctx);
/* silence_ms > 0: a frame after at least that much silence from a DOWN link's neighbour marks it returned. */
void sf_link_note_heard(struct sf_link *l, int64_t now, uint32_t silence_ms);
void sf_link_probe_ok(struct sf_link *l, int64_t now, uint8_t n_up, uint32_t probe_fast_ms,
		      sf_link_fn on_change, void *ctx);
void sf_link_fail(struct sf_link *l, int64_t now, const char *reason, uint32_t hold_min_ms,
		  uint32_t hold_max_ms, uint32_t hold_reset_ms, uint32_t t_probe_ms,
		  sf_link_fn on_change, void *ctx);
void sf_link_force_probe(struct sf_link *l, int64_t now, sf_link_fn on_change, void *ctx);

#endif /* SF_LINK_H_ */
