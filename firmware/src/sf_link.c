/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "sf_link.h"

void sf_link_init(struct sf_link_table *t)
{
	unsigned int i;

	for (i = 0; i < SF_LINK_CAP; i++) {
		t->item[i].used = false;
	}
}

struct sf_link *sf_link_find(struct sf_link_table *t, uint16_t next_id)
{
	unsigned int i;

	for (i = 0; i < SF_LINK_CAP; i++) {
		if (t->item[i].used && t->item[i].next_id == next_id) {
			return &t->item[i];
		}
	}
	return NULL;
}

struct sf_link *sf_link_ensure(struct sf_link_table *t, uint16_t next_id, int64_t now,
			       bool assume_up)
{
	struct sf_link *l = sf_link_find(t, next_id);
	unsigned int i;

	if (next_id == 0 || next_id == SF_ID_BCAST) {
		return NULL;
	}
	if (l != NULL) {
		return l;
	}
	for (i = 0; i < SF_LINK_CAP; i++) {
		if (!t->item[i].used) {
			l = &t->item[i];
			break;
		}
	}
	if (l == NULL) {
		return NULL;
	}
	l->used = true;
	l->next_id = next_id;
	l->state = assume_up ? SF_LINK_UP : SF_LINK_DOWN;
	l->consec = 0;
	l->down_streak = 0;
	l->heard = false;
	l->last_heard_ms = 0;
	l->returned = false;
	l->hold_until_ms = now;
	l->up_since_ms = now;
	l->next_probe_ms = now;
	return l;
}

static uint32_t hold_ms(uint8_t streak, uint32_t min_ms, uint32_t max_ms)
{
	uint32_t h = min_ms;
	uint8_t i;

	if (streak < 1) {
		streak = 1;
	}
	for (i = 1; i < streak; i++) {
		if (max_ms > 0 && h > max_ms / 2u) {
			return max_ms;
		}
		h *= 2u;
	}
	if (max_ms > 0 && h > max_ms) {
		return max_ms;
	}
	return h;
}

static void change(struct sf_link *l, uint8_t next, const char *reason, sf_link_fn fn, void *ctx)
{
	uint8_t old = l->state;

	l->state = next;
	if (fn != NULL && old != next) {
		fn(ctx, l, old, reason);
	}
}

void sf_link_fail(struct sf_link *l, int64_t now, const char *reason, uint32_t hold_min_ms,
		  uint32_t hold_max_ms, uint32_t hold_reset_ms, uint32_t t_probe_ms,
		  sf_link_fn on_change, void *ctx)
{
	uint8_t streak;

	if (l == NULL) {
		return;
	}
	if (l->state == SF_LINK_UP && hold_reset_ms > 0 &&
	    (now - l->up_since_ms) >= (int64_t)hold_reset_ms) {
		streak = 1;
	} else {
		streak = (uint8_t)(l->down_streak + 1u);
		if (streak == 0) {
			streak = 255;
		}
	}
	l->down_streak = streak;
	l->consec = 0;
	l->heard = false;
	l->returned = false;
	l->hold_until_ms = now + (int64_t)hold_ms(streak, hold_min_ms, hold_max_ms);
	l->next_probe_ms = l->hold_until_ms + (int64_t)t_probe_ms;
	change(l, SF_LINK_DOWN, reason, on_change, ctx);
}

void sf_link_tick(struct sf_link_table *t, int64_t now, uint32_t hello_dead_ms, uint32_t t_probe_ms,
		  uint32_t hold_min_ms, uint32_t hold_max_ms, uint32_t hold_reset_ms,
		  sf_link_fn on_change, void *ctx)
{
	unsigned int i;

	for (i = 0; i < SF_LINK_CAP; i++) {
		struct sf_link *l = &t->item[i];

		if (!l->used) {
			continue;
		}
		if (l->state == SF_LINK_UP && hello_dead_ms > 0 && l->heard &&
		    (now - l->last_heard_ms) > (int64_t)hello_dead_ms) {
			l->heard = false;
			sf_link_fail(l, now, "hello_dead", hold_min_ms, hold_max_ms, hold_reset_ms,
				     t_probe_ms, on_change, ctx);
			continue;
		}
		if (l->state == SF_LINK_DOWN && l->returned) {
			/* A neighbour that was silent is audible again: probe now, the hold-down was
			 * meant for a link that keeps failing, not for one that was simply gone.
			 */
			l->returned = false;
			l->consec = 0;
			l->next_probe_ms = now;
			change(l, SF_LINK_PROBING, "returned", on_change, ctx);
			continue;
		}
		if (l->state == SF_LINK_DOWN && now >= l->hold_until_ms) {
			bool timer = (t_probe_ms == 0) || (now >= l->next_probe_ms);

			if (l->heard || timer) {
				l->consec = 0;
				l->next_probe_ms = now;
				change(l, SF_LINK_PROBING, l->heard ? "hello" : "t_probe",
				       on_change, ctx);
			}
		}
	}
}

void sf_link_note_heard(struct sf_link *l, int64_t now, uint32_t silence_ms)
{
	if (l == NULL) {
		return;
	}
	if (silence_ms > 0 && l->state == SF_LINK_DOWN && l->last_heard_ms != 0 &&
	    (now - l->last_heard_ms) >= (int64_t)silence_ms) {
		l->returned = true;
	}
	l->heard = true;
	l->last_heard_ms = now;
}

void sf_link_probe_ok(struct sf_link *l, int64_t now, uint8_t n_up, uint32_t probe_fast_ms,
		      sf_link_fn on_change, void *ctx)
{
	if (l == NULL) {
		return;
	}
	if (n_up == 0) {
		n_up = 1;
	}
	l->consec++;
	l->next_probe_ms = now + (int64_t)probe_fast_ms;
	if (l->state == SF_LINK_PROBING && l->consec >= n_up) {
		l->up_since_ms = now;
		change(l, SF_LINK_UP, "probes", on_change, ctx);
	}
}

void sf_link_force_probe(struct sf_link *l, int64_t now, sf_link_fn on_change, void *ctx)
{
	if (l == NULL) {
		return;
	}
	l->consec = 0;
	l->hold_until_ms = now;
	l->next_probe_ms = now;
	l->heard = true;
	l->last_heard_ms = now;
	if (l->state != SF_LINK_PROBING) {
		change(l, SF_LINK_PROBING, "neighbor_reset", on_change, ctx);
	}
}
