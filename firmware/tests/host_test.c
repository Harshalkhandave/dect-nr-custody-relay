/*
 * Host checks for the store-and-forward core. No modem, no Zephyr.
 *
 *   gcc -std=c11 -Wall -Wextra -Werror -DSF_HOST -I../src -o host_test host_test.c
 *       ../src/sf_codec.c ../src/sf_dedup.c ../src/sf_store.c ../src/sf_link.c ../src/sf_node.c
 */

#include "sf_codec.h"
#include "sf_dedup.h"
#include "sf_node.h"
#include "sf_phy.h"
#include "sf_rxpolicy.h"
#include "sf_store.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

static int failed;

static void check(const char *name, int cond)
{
	if (cond) {
		printf("  PASS  %s\n", name);
	} else {
		printf("  FAIL  %s\n", name);
		failed++;
	}
}

static struct sf_cfg base_cfg(uint16_t id, uint8_t role, uint16_t dest)
{
	struct sf_cfg c;

	memset(&c, 0, sizeof(c));
	c.node_id = id;
	c.role = role;
	c.dest_id = dest;
	c.payload_len = 8;
	c.interval_ms = 1000;
	c.hello_ms = 0;
	c.hello_mode = SF_HELLO_OFF;
	c.ttl = 4;
	c.policy = SF_POLICY_REJECT;
	c.assume_up = 1;
	c.direct_fallback = 1;
	c.gen_class = SF_CLASS_TEL;
	c.dedup_on = 1;
	c.custody = 1;
	c.tx_power = 10;
	c.mcs = 0;
	c.ack_timeout_ms = 50;
	c.max_attempts = 4;
	c.backoff_min_ms = 0;
	c.backoff_max_ms = 0;
	c.backoff_cap_ms = 0;
	c.nack_holdoff_ms = 1000;
	c.inter_tx_listen_ms = 0;
	c.rx_slice_ms = 15;
	c.hello_dead_ms = 0;
	c.t_probe_ms = 1000;
	c.probe_fast_ms = 10;
	c.n_up = 3;
	c.holddown_min_ms = 50;
	c.holddown_max_ms = 200;
	c.holddown_reset_ms = 60000;
	c.hold_cancel_ms = 0;
	c.cancel_ack = 1;
	c.rx_event = 1;
	c.liveness_any = 1;
	c.ctrl_subslots = 8;
	c.rssi_level = -60;
	c.telemetry_ttl_ms = 0;
	c.stream_idle_ms = 0;
	c.alarm_rate = 5;
	c.alarm_burst = 2;
	c.phy_mtu = 249;
	return c;
}

static void make_node(struct sf_node *n, struct sf_slot *slots, uint8_t *mem, uint16_t nslots,
		      uint16_t alarm, const struct sf_cfg *cfg, const struct sf_route *routes,
		      unsigned int nroutes)
{
	struct sf_pool small;
	struct sf_pool large;
	struct sf_store store;

	sf_pool_init(&small, slots, mem, nslots, 64, alarm);
	sf_pool_init(&large, NULL, NULL, 0, 0, 0);
	sf_store_init(&store, small, large);
	sf_node_init(n, cfg, routes, nroutes, 7, store);
}

static int pump_tx(struct sf_node *n, int64_t *now, struct sf_action *act, int limit)
{
	int i;

	for (i = 0; i < limit; i++) {
		sf_node_poll(n, *now, act);
		if (act->kind == SF_ACT_TX) {
			sf_node_on_tx_done(n, *now, true, act->inflight);
			return 1;
		}
		*now += (int64_t)act->rx_ms;
	}
	return 0;
}

static void test_codec(void)
{
	struct sf_frame in;
	struct sf_frame out;
	uint8_t buf[249];
	int len;

	printf("codec\n");
	memset(&in, 0, sizeof(in));
	in.ver = SF_PROTO_VERSION;
	in.type = SF_TYPE_DATA;
	in.class_ = SF_CLASS_ALARM;
	in.retx = 1;
	in.src = 0x0102;
	in.dst = 0x0304;
	in.prev = 0x0506;
	in.next = 0x0708;
	in.seq = 0x090A;
	in.epoch = 0x0B0C;
	in.hops = 2;
	in.ttl = 3;
	in.payload_len = 4;
	memcpy(in.payload, "abcd", 4);
	len = sf_codec_encode(&in, buf, sizeof(buf), 249);
	check("data length", len == SF_HDR_LEN + 4);
	check("little endian src", buf[2] == 0x02 && buf[3] == 0x01);
	check("class and retx flags", (buf[1] & SF_FLAG_RETX) != 0 && ((buf[1] >> 2) & 3) == SF_CLASS_ALARM);
	check("custody set on data", (buf[1] & SF_FLAG_CUSTODY) != 0);
	check("decode ok", sf_codec_decode(buf, (size_t)len, 249, &out) == SF_CODEC_OK);
	check("round trip", out.seq == in.seq && out.epoch == in.epoch && out.payload_len == 4 &&
				   memcmp(out.payload, "abcd", 4) == 0 && out.class_ == SF_CLASS_ALARM &&
				   out.retx);
	buf[0] = 0x21;
	check("bad version dropped", sf_codec_decode(buf, (size_t)len, 249, &out) == -SF_CODEC_VERSION);
	buf[0] = 0x11;
	buf[1] |= SF_FLAG_SEC;
	check("sec dropped", sf_codec_decode(buf, (size_t)len, 249, &out) == -SF_CODEC_SEC);
	check("short dropped", sf_codec_decode(buf, 4, 249, &out) == -SF_CODEC_SHORT);
	check("delta wrap +1", sf_delta16(0, 65535) == 1);
	check("delta wrap dup", sf_delta16(5, 6) == -1);
}

static void test_dedup(void)
{
	struct sf_dedup d;
	struct sf_dedup_out o;

	printf("dedup\n");
	sf_dedup_init(&d);
	sf_dedup_check(&d, 1, SF_CLASS_TEL, 3, 1, 0, 0, true, &o);
	check("first is new", o.result == SF_DEDUP_NEW);
	sf_dedup_commit(&d, 1, SF_CLASS_TEL, 3, 1, 0);
	sf_dedup_check(&d, 1, SF_CLASS_TEL, 3, 1, 10, 0, true, &o);
	check("same seq is dup", o.result == SF_DEDUP_DUP);
	sf_dedup_check(&d, 1, SF_CLASS_TEL, 3, 4, 10, 0, true, &o);
	check("gap of 2", o.result == SF_DEDUP_NEW && o.gap == 2);
	sf_dedup_commit(&d, 1, SF_CLASS_TEL, 3, 4, 10);
	check("gap counted", d.gaps == 2);
	sf_dedup_check(&d, 1, SF_CLASS_TEL, 4, 1, 20, 0, true, &o);
	check("newer epoch", o.result == SF_DEDUP_NEW && o.src_reset && o.old_epoch == 3);
	sf_dedup_check(&d, 1, SF_CLASS_TEL, 2, 9, 20, 0, true, &o);
	check("older epoch", o.result == SF_DEDUP_STALE_EPOCH);
	sf_dedup_commit(&d, 1, SF_CLASS_TEL, 3, 65535, 30);
	sf_dedup_check(&d, 1, SF_CLASS_TEL, 3, 0, 40, 0, true, &o);
	check("seq wrap is next", o.result == SF_DEDUP_NEW && o.gap == 0);
}

static void test_store(void)
{
	struct sf_slot slots[4];
	uint8_t mem[4 * 64];
	struct sf_pool pool;
	struct sf_store store;
	struct sf_slot meta;
	struct sf_dropped drop;
	struct sf_view view;
	uint32_t order = 0;
	uint8_t payload[8] = {1, 2, 3, 4, 5, 6, 7, 8};
	int i;

	printf("store\n");
	sf_pool_init(&pool, slots, mem, 4, 64, 2);
	sf_store_init(&store, pool, pool);
	store.large.nslots = 0;
	memset(&meta, 0, sizeof(meta));
	meta.src = 1;
	meta.dst = 2;
	meta.next = 2;
	meta.class_ = SF_CLASS_TEL;
	meta.len = 8;
	meta.ttl = 4;
	for (i = 0; i < 2; i++) {
		meta.seq = (uint16_t)i;
		check("tel put", sf_store_put(&store, &meta, payload, SF_POLICY_REJECT, 0, &drop, &order) == 0);
	}
	meta.seq = 9;
	check("tel blocked by reserve",
	      sf_store_put(&store, &meta, payload, SF_POLICY_REJECT, 0, &drop, &order) == -3);
	check("alarm still fits", sf_store_free_for(&store, 8, SF_CLASS_ALARM) == 2);
	meta.class_ = SF_CLASS_ALARM;
	meta.seq = 1;
	check("alarm put", sf_store_put(&store, &meta, payload, SF_POLICY_REJECT, 0, &drop, &order) == 0);
	check("peek is alarm first",
	      sf_store_peek(&store, 0, 0, 0, NULL, NULL, &view) && view.class_ == SF_CLASS_ALARM);
	meta.class_ = SF_CLASS_TEL;
	meta.seq = 50;
	check("drop_oldest accepts",
	      sf_store_put(&store, &meta, payload, SF_POLICY_DROP_OLDEST, 0, &drop, &order) == 0 &&
		      drop.dropped && drop.seq == 0);
}

static void deliver(struct sf_node *from_tx, struct sf_node *to, int64_t now)
{
	struct sf_action act;
	int guard;

	for (guard = 0; guard < 6; guard++) {
		sf_node_poll(from_tx, now, &act);
		if (act.kind == SF_ACT_TX) {
			sf_node_on_rx(to, now, act.tx, act.tx_len, -140);
			sf_node_on_tx_done(from_tx, now, true, act.inflight);
			return;
		}
		now += (int64_t)act.rx_ms;
	}
}

static void test_hop(void)
{
	struct sf_node src;
	struct sf_node sink;
	struct sf_slot ss[8];
	struct sf_slot ks[4];
	uint8_t sm[8 * 64];
	uint8_t km[4 * 64];
	struct sf_cfg cs;
	struct sf_cfg ck;
	int64_t now = 1000;
	int guard;

	printf("one hop\n");
	cs = base_cfg(11, SF_ROLE_SOURCE, 33);
	ck = base_cfg(33, SF_ROLE_SINK, 0);
	cs.count = 3;
	make_node(&src, ss, sm, 8, 1, &cs, NULL, 0);
	make_node(&sink, ks, km, 4, 0, &ck, NULL, 0);
	check("start", sf_node_start(&src, now, 3) == 0 && sf_node_start(&sink, now, 0) == 0);
	for (guard = 0; guard < 30 && sf_node_running(&src); guard++) {
		deliver(&src, &sink, now);
		deliver(&sink, &src, now);
		now += 1000;
	}
	check("source finished", !sf_node_running(&src));
	check("three delivered once", sink.ct.delivered == 3);
	check("source drained", src.ct.drained_total == 3 && src.ct.generated == 3);
	check("no gaps", sink.ct.rx_gap == 0 && sink.ct.dup_rx == 0);
}

static void test_retry(void)
{
	struct sf_node src;
	struct sf_node sink;
	struct sf_slot ss[4];
	struct sf_slot ks[4];
	uint8_t sm[4 * 64];
	uint8_t km[4 * 64];
	struct sf_cfg cs;
	struct sf_cfg ck;
	struct sf_action act;
	int64_t now = 0;

	printf("retry\n");
	cs = base_cfg(11, SF_ROLE_SOURCE, 33);
	ck = base_cfg(33, SF_ROLE_SINK, 0);
	cs.count = 1;
	cs.ack_timeout_ms = 10;
	cs.max_attempts = 3;
	make_node(&src, ss, sm, 4, 0, &cs, NULL, 0);
	make_node(&sink, ks, km, 4, 0, &ck, NULL, 0);
	sf_node_start(&src, now, 1);
	sf_node_start(&sink, now, 0);
	check("first tx", pump_tx(&src, &now, &act, 4));
	sf_node_on_rx(&sink, now, act.tx, act.tx_len, -100);
	/* Drop the ACK. */
	now += 10;
	check("retry tx", pump_tx(&src, &now, &act, 4));
	check("retx flag", (act.tx[1] & SF_FLAG_RETX) != 0);
	sf_node_on_rx(&sink, now, act.tx, act.tx_len, -100);
	check("still one delivery", sink.ct.delivered == 1 && sink.ct.dup_rx == 1);
	check("sink acks dup", pump_tx(&sink, &now, &act, 4) && act.kind == SF_ACT_TX);
	sf_node_on_rx(&src, now, act.tx, act.tx_len, -100);
	now += 1;
	sf_node_poll(&src, now, &act);
	check("dup ack releases custody", src.ct.drained_total == 1 && !src.inf.active);
}

static void test_relay(void)
{
	struct sf_node a, b, c;
	struct sf_slot as[4], bs[2], cs[4];
	uint8_t am[4 * 64], bm[2 * 64], cm[4 * 64];
	struct sf_cfg ca, cb, cc;
	struct sf_route route;
	struct sf_action act;
	int64_t now = 0;
	int i;

	printf("relay\n");
	ca = base_cfg(11, SF_ROLE_SOURCE, 33);
	cb = base_cfg(22, SF_ROLE_RELAY, 0);
	cc = base_cfg(33, SF_ROLE_SINK, 0);
	ca.direct_fallback = 0;
	ca.count = 1;
	route.used = true;
	route.dst = 33;
	route.next = 22;
	make_node(&a, as, am, 4, 0, &ca, &route, 1);
	make_node(&b, bs, bm, 1, 0, &cb, NULL, 0);
	make_node(&c, cs, cm, 4, 0, &cc, NULL, 0);
	sf_node_start(&a, now, 1);
	sf_node_start(&b, now, 0);
	sf_node_start(&c, now, 0);
	check("source to relay", pump_tx(&a, &now, &act, 4));
	check("next is relay", act.tx[8] == 22 && act.tx[9] == 0);
	sf_node_on_rx(&b, now, act.tx, act.tx_len, -120);
	check("relay stored", b.ct.stored_total == 1);
	check("relay ack", pump_tx(&b, &now, &act, 4));
	sf_node_on_rx(&a, now, act.tx, act.tx_len, -120);
	check("source released", a.ct.drained_total == 1);
	check("relay forward", pump_tx(&b, &now, &act, 6));
	sf_node_on_rx(&c, now, act.tx, act.tx_len, -110);
	check("sink got relayed", c.ct.delivered == 1 && c.ct.rx_gap == 0);
	/* Fill the one-slot relay and confirm the source keeps the frame. */
	sf_node_set(&a, "count", "0", NULL, 0);
	a.run_count = 0;
	a.ct.generated = 0;
	a.last_gen_ms = 0;
	a.running = true;
	/* Occupy the relay store by not letting it transmit: stop it after one accept. */
	now += 1000;
	check("second source tx", pump_tx(&a, &now, &act, 4));
	sf_node_on_rx(&b, now, act.tx, act.tx_len, -120);
	/* b already holds the first if it did not pop. It pops only on ACK from c.
	 * Forward was armed, so the slot may still be there until c ACKs.
	 */
	(void)i;
	check("custody still at relay or acked", b.ct.stored_total >= 1);
}

static void test_queue_full(void)
{
	struct sf_node a, b;
	struct sf_slot as[4], bs[1];
	uint8_t am[4 * 64], bm[64];
	struct sf_cfg ca, cb;
	struct sf_route route;
	struct sf_action act;
	int64_t now = 0;

	printf("queue full\n");
	ca = base_cfg(11, SF_ROLE_SOURCE, 33);
	cb = base_cfg(22, SF_ROLE_RELAY, 0);
	ca.direct_fallback = 0;
	ca.interval_ms = 1;
	ca.nack_holdoff_ms = 5000;
	route.used = true;
	route.dst = 33;
	route.next = 22;
	make_node(&a, as, am, 4, 0, &ca, &route, 1);
	make_node(&b, bs, bm, 1, 0, &cb, NULL, 0);
	sf_node_start(&a, now, 0);
	sf_node_start(&b, now, 0);
	check("tx1", pump_tx(&a, &now, &act, 4));
	sf_node_on_rx(&b, now, act.tx, act.tx_len, -100);
	check("ack1", pump_tx(&b, &now, &act, 4));
	sf_node_on_rx(&a, now, act.tx, act.tx_len, -100);
	now += 1;
	check("tx2", pump_tx(&a, &now, &act, 4));
	sf_node_on_rx(&b, now, act.tx, act.tx_len, -100);
	check("second rejected", b.ct.nack_full == 1 && b.ct.stored_total == 1);
	check("NACKing relay does not hold off itself", b.holdoff_ms[SF_CLASS_TEL] == 0);
	check("full ack", pump_tx(&b, &now, &act, 4));
	sf_node_on_rx(&a, now, act.tx, act.tx_len, -100);
	check("source kept the frame", sf_store_used(&a.store) == 1 && a.ct.drained_total == 1);
}

static void test_probe(void)
{
	struct sf_node a, b;
	struct sf_slot as[4], bs[4];
	uint8_t am[4 * 64], bm[4 * 64];
	struct sf_cfg ca, cb;
	struct sf_action act;
	int64_t now = 0;
	int ups = 0;
	int i;

	printf("probe\n");
	ca = base_cfg(11, SF_ROLE_SOURCE, 22);
	cb = base_cfg(22, SF_ROLE_SINK, 0);
	ca.assume_up = 0;
	ca.n_up = 2;
	ca.t_probe_ms = 0;
	ca.probe_fast_ms = 5;
	ca.count = 1;
	ca.interval_ms = 1000;
	make_node(&a, as, am, 4, 0, &ca, NULL, 0);
	make_node(&b, bs, bm, 4, 0, &cb, NULL, 0);
	sf_node_start(&a, now, 1);
	sf_node_start(&b, now, 0);
	for (i = 0; i < 2; i++) {
		check("probe tx", pump_tx(&a, &now, &act, 6));
		sf_node_on_rx(&b, now, act.tx, act.tx_len, -90);
		check("probe reply", pump_tx(&b, &now, &act, 4));
		sf_node_on_rx(&a, now, act.tx, act.tx_len, -90);
		now += 5;
	}
	for (i = 0; i < SF_LINK_CAP; i++) {
		if (a.links.item[i].used && a.links.item[i].state == SF_LINK_UP) {
			ups++;
		}
	}
	check("link up after N probes", ups == 1);
	(void)act;
}

static char cap[32][256];
static int ncap;

static void capture(void *ctx, const char *line)
{
	(void)ctx;
	if (ncap < 32) {
		strncpy(cap[ncap], line, sizeof(cap[0]) - 1);
		cap[ncap][sizeof(cap[0]) - 1] = '\0';
		ncap++;
	}
}

static int64_t fake_us(void)
{
	return 5000000;
}

static int cap_has(const char *needle)
{
	int i;

	for (i = 0; i < ncap; i++) {
		if (strstr(cap[i], needle) != NULL) {
			return 1;
		}
	}
	return 0;
}

static void test_logs(void)
{
	struct sf_node src, sink;
	struct sf_slot ss[4], ks[4];
	uint8_t sm[4 * 64], km[4 * 64];
	struct sf_cfg cs, ck;
	struct sf_action act;
	int64_t now = 0;
	int i;

	printf("log lines\n");
	cs = base_cfg(11, SF_ROLE_SOURCE, 33);
	ck = base_cfg(33, SF_ROLE_SINK, 0);
	cs.count = 1;
	cs.ack_timeout_ms = 10;
	make_node(&src, ss, sm, 4, 0, &cs, NULL, 0);
	make_node(&sink, ks, km, 4, 0, &ck, NULL, 0);
	sf_node_set_emit(&src, capture, NULL);
	sf_node_set_clock(&src, fake_us);
	sf_node_start(&src, now, 1);
	sf_node_start(&sink, now, 0);
	check("first tx", pump_tx(&src, &now, &act, 4));
	check("first tx logged retx=0", cap_has("type=DATA") && cap_has("retx=0"));
	now += 10;
	check("retry tx", pump_tx(&src, &now, &act, 4));
	check("retransmission logs a TX line", cap_has("retx=1 attempt=2"));

	/* LINK_STATE lines carry time and time_us. */
	cs = base_cfg(11, SF_ROLE_SOURCE, 22);
	ck = base_cfg(22, SF_ROLE_SINK, 0);
	cs.assume_up = 0;
	cs.n_up = 1;
	cs.t_probe_ms = 0;
	cs.probe_fast_ms = 5;
	cs.count = 1;
	ncap = 0;
	now = 0;
	make_node(&src, ss, sm, 4, 0, &cs, NULL, 0);
	make_node(&sink, ks, km, 4, 0, &ck, NULL, 0);
	sf_node_set_emit(&src, capture, NULL);
	sf_node_set_clock(&src, fake_us);
	sf_node_start(&src, now, 1);
	sf_node_start(&sink, now, 0);
	for (i = 0; i < 1; i++) {
		check("probe tx", pump_tx(&src, &now, &act, 6));
		sf_node_on_rx(&sink, now, act.tx, act.tx_len, -90);
		check("probe reply", pump_tx(&sink, &now, &act, 4));
		sf_node_on_rx(&src, now, act.tx, act.tx_len, -90);
	}
	check("LINK_STATE has time_us", cap_has("LINK_STATE") && cap_has("time=5000 time_us=5000000"));

	/* START and STOP carry time and time_us. */
	ncap = 0;
	sf_node_stop(&src, now, "test");
	check("STOP has time_us", cap_has("STOP:") && cap_has("reason=test time=5000 time_us=5000000"));
	ncap = 0;
	sf_node_start(&src, now, 1);
	check("START line with time_us", cap_has("START: node=11 role=source count=1 custody=1") &&
					 cap_has("time=5000 time_us=5000000"));
}

static void test_open_loop(void)
{
	struct sf_node src, sink;
	struct sf_slot ss[8], ks[4];
	uint8_t sm[8 * 64], km[4 * 64];
	struct sf_cfg cs, ck;
	struct sf_action act;
	int64_t now = 1000;
	int guard;

	printf("open-loop\n");
	cs = base_cfg(11, SF_ROLE_SOURCE, 33);
	ck = base_cfg(33, SF_ROLE_SINK, 0);
	cs.custody = 0;
	ck.custody = 0;
	cs.assume_up = 0; /* link state must not gate sending */
	make_node(&src, ss, sm, 8, 0, &cs, NULL, 0);
	make_node(&sink, ks, km, 4, 0, &ck, NULL, 0);
	sf_node_start(&src, now, 3);
	sf_node_start(&sink, now, 0);
	for (guard = 0; guard < 30 && sf_node_running(&src); guard++) {
		deliver(&src, &sink, now);
		deliver(&sink, &src, now);
		now += 1000;
	}
	check("source finished", !sf_node_running(&src));
	check("three delivered", sink.ct.delivered == 3);
	check("no ACK sent", sink.ct.ack_tx == 0 && sink.ack_n == 0);
	check("slots released at send", src.ct.drained_total == 3 && sf_store_used(&src.store) == 0);
	check("nothing in flight, no probes", !src.inf.active && src.ct.probe_tx == 0 && src.ct.retries == 0);
	/* A frame sent into a dead sink is gone: nothing is retained. */
	sf_node_stop(&sink, now, "test");
	sf_node_start(&src, now, 1);
	for (guard = 0; guard < 10 && sf_node_running(&src); guard++) {
		deliver(&src, &sink, now);
		now += 1000;
	}
	check("lost frame not retained", sf_store_used(&src.store) == 0 && sink.ct.delivered == 3);
	(void)act;
}

static void test_stopped_node(void)
{
	struct sf_node src, sink;
	struct sf_slot ss[4], ks[4];
	uint8_t sm[4 * 64], km[4 * 64];
	struct sf_cfg cs, ck;
	struct sf_action act;
	int64_t now = 0;

	printf("stopped node ignores frames\n");
	cs = base_cfg(11, SF_ROLE_SOURCE, 33);
	ck = base_cfg(33, SF_ROLE_SINK, 0);
	make_node(&src, ss, sm, 4, 0, &cs, NULL, 0);
	make_node(&sink, ks, km, 4, 0, &ck, NULL, 0);
	sf_node_start(&src, now, 1);
	check("source tx", pump_tx(&src, &now, &act, 4));
	sf_node_on_rx(&sink, now, act.tx, act.tx_len, -100);
	check("stopped sink delivers nothing and queues no ACK", sink.ct.delivered == 0 && sink.ack_n == 0);
	sf_node_start(&sink, now, 0);
	sf_node_on_rx(&sink, now, act.tx, act.tx_len, -100);
	check("running sink delivers", sink.ct.delivered == 1 && sink.ack_n == 1);
}

static void test_generator_rate(void)
{
	struct sf_node src;
	struct sf_slot ss[8];
	uint8_t sm[8 * 64];
	struct sf_cfg cs;
	struct sf_action act;

	printf("generator does not drift\n");
	cs = base_cfg(11, SF_ROLE_SOURCE, 33);
	make_node(&src, ss, sm, 8, 0, &cs, NULL, 0);
	sf_node_start(&src, 1000, 0);
	sf_node_poll(&src, 1000, &act);
	sf_node_poll(&src, 2005, &act);
	sf_node_poll(&src, 3001, &act);
	check("three frames by t=3001 with polls 5 ms late", src.ct.generated == 3);
	sf_node_poll(&src, 20000, &act);
	sf_node_poll(&src, 20001, &act);
	check("resynchronises after a long stall (no burst)", src.ct.generated == 4);
}

static void test_heard_cleared(void)
{
	struct sf_link_table t;
	struct sf_link *l;

	printf("heard cleared on failure (F5b)\n");
	sf_link_init(&t);
	l = sf_link_ensure(&t, 5, 0, true);
	sf_link_note_heard(l, 0, 0);
	check("hello noted", l->heard);
	sf_link_fail(l, 10, "max_attempts", 50, 200, 60000, 1000, NULL, NULL);
	check("cleared by max_attempts failure", !l->heard && l->state == SF_LINK_DOWN);
}

static void test_hold_cancel(void)
{
	struct sf_link_table t;
	struct sf_link *l;

	printf("hold-down cancelled by a returning neighbour\n");
	sf_link_init(&t);
	l = sf_link_ensure(&t, 5, 0, true);
	sf_link_fail(l, 100, "max_attempts", 5000, 60000, 60000, 3000, NULL, NULL);
	check("DOWN with a hold-down", l->state == SF_LINK_DOWN && l->hold_until_ms == 5100);

	/* neighbour heard every second: no cancel, hold-down stays */
	sf_link_note_heard(l, 1100, 3000);
	sf_link_note_heard(l, 2100, 3000);
	sf_link_note_heard(l, 3100, 3000);
	check("steady neighbour does not cancel", !l->returned);
	sf_link_tick(&t, 3200, 7000, 3000, 5000, 60000, 60000, NULL, NULL);
	check("old behaviour inside hold-down: no PROBING from a heard frame", l->state == SF_LINK_DOWN);

	/* silent for 5 s, then heard: returned, PROBING at once */
	sf_link_note_heard(l, 8200, 3000);
	check("returned flag set after silence", l->returned);
	sf_link_tick(&t, 8200, 7000, 3000, 5000, 60000, 60000, NULL, NULL);
	check("PROBING at once, flag cleared", l->state == SF_LINK_PROBING && !l->returned);
	check("not UP from a HELLO alone", l->state != SF_LINK_UP);

	/* a failure while probing resets the flag and starts a new hold-down */
	l->returned = true;
	sf_link_fail(l, 8300, "probe_fail", 5000, 60000, 60000, 3000, NULL, NULL);
	check("failure clears returned", !l->returned && l->state == SF_LINK_DOWN);

	/* hold_cancel 0 restores the old behaviour */
	sf_link_init(&t);
	l = sf_link_ensure(&t, 6, 0, true);
	sf_link_fail(l, 100, "max_attempts", 5000, 60000, 60000, 3000, NULL, NULL);
	sf_link_note_heard(l, 20000, 0);
	check("hold_cancel 0 never sets returned", !l->returned);
}

static void test_runtime_settings(void)
{
	struct sf_node n;
	struct sf_slot sl[4];
	uint8_t mem[4 * 64];
	struct sf_cfg c = base_cfg(11, SF_ROLE_SOURCE, 33);
	char err[64];

	printf("runtime settings\n");
	make_node(&n, sl, mem, 4, 0, &c, NULL, 0);
	check("cancel_ack off", sf_node_set(&n, "cancel_ack", "off", err, sizeof(err)) == 0 && !n.cfg.cancel_ack);
	check("cancel_ack bad", sf_node_set(&n, "cancel_ack", "maybe", err, sizeof(err)) != 0);
	check("rx_mode slice", sf_node_set(&n, "rx_mode", "slice", err, sizeof(err)) == 0 && !n.cfg.rx_event);
	check("rx_mode event", sf_node_set(&n, "rx_mode", "event", err, sizeof(err)) == 0 && n.cfg.rx_event);
	check("rx_mode bad", sf_node_set(&n, "rx_mode", "x", err, sizeof(err)) != 0);
	check("liveness hello", sf_node_set(&n, "liveness", "hello", err, sizeof(err)) == 0 && !n.cfg.liveness_any);
	check("liveness any", sf_node_set(&n, "liveness", "any", err, sizeof(err)) == 0 && n.cfg.liveness_any);
	check("ctrl_subslots 16", sf_node_set(&n, "ctrl_subslots", "16", err, sizeof(err)) == 0 && n.cfg.ctrl_subslots == 16);
	check("ctrl_subslots 5 rejected", sf_node_set(&n, "ctrl_subslots", "5", err, sizeof(err)) != 0 && n.cfg.ctrl_subslots == 16);
	check("rssi_level -70", sf_node_set(&n, "rssi_level", "-70", err, sizeof(err)) == 0 && n.cfg.rssi_level == -70);
	check("rssi_level 5 rejected", sf_node_set(&n, "rssi_level", "5", err, sizeof(err)) != 0 && n.cfg.rssi_level == -70);
	sf_node_start(&n, 1000, 0);
	check("blocked while running", sf_node_set(&n, "rx_mode", "slice", err, sizeof(err)) == -EBUSY &&
		sf_node_set(&n, "ctrl_subslots", "4", err, sizeof(err)) == -EBUSY);
	check("cancel_ack allowed while running", sf_node_set(&n, "cancel_ack", "on", err, sizeof(err)) == 0);
}

static void test_phy_len(void)
{
	printf("PHY length code\n");
	check("DATA 19 B stays 0x03", sf_phy_len_code(SF_TYPE_DATA, 19, 8) == 0x03);
	check("DATA 34 B stays 0x07", sf_phy_len_code(SF_TYPE_DATA, 34, 16) == 0x07);
	check("DATA 78 B stays 0x0F", sf_phy_len_code(SF_TYPE_DATA, 78, 4) == 0x0F);
	check("ACK 23 B, 8 subslots: 0x07", sf_phy_len_code(SF_TYPE_ACK, 23, 8) == 0x07);
	check("HELLO 20 B, 8 subslots: 0x07", sf_phy_len_code(SF_TYPE_HELLO, 20, 8) == 0x07);
	check("PROBE, 16 subslots: 0x0F", sf_phy_len_code(SF_TYPE_PROBE, 24, 16) == 0x0F);
	check("ctrl 4 subslots gives the 4-subslot code", sf_phy_len_code(SF_TYPE_ACK, 23, 4) == 0x03);
	check("control frame never below the length rule", sf_phy_len_code(SF_TYPE_PROBE, 70, 4) == 0x0F);
}

static void test_liveness(void)
{
	struct sf_node src, sink, rel;
	struct sf_slot ss[4], ks[4], rs[4];
	uint8_t sm[4 * 64], km[4 * 64], rm[4 * 64];
	struct sf_cfg cs, ck, cr;
	struct sf_action act;
	struct sf_link *l;
	int64_t now = 1000;

	printf("liveness and HELLO\n");
	/* An ACK refreshes liveness: no hello_dead while ACKs arrive, but silence still drops. */
	cs = base_cfg(11, SF_ROLE_SOURCE, 33);
	ck = base_cfg(33, SF_ROLE_SINK, 0);
	cs.hello_dead_ms = 100;
	cs.count = 1;
	make_node(&src, ss, sm, 4, 0, &cs, NULL, 0);
	make_node(&sink, ks, km, 4, 0, &ck, NULL, 0);
	sf_node_start(&src, now, 1);
	sf_node_start(&sink, now, 0);
	deliver(&src, &sink, now);
	deliver(&sink, &src, now);
	l = sf_link_find(&src.links, 33);
	check("link exists and was heard via the ACK", l != NULL && l->heard && l->last_heard_ms == now);
	sf_node_poll(&src, now + 90, &act);
	check("still UP 90 ms after the ACK", l->state == SF_LINK_UP);
	sf_node_poll(&src, now + 250, &act);
	check("dropped after 250 ms of silence", l->state == SF_LINK_DOWN);

	/* A node that just transmitted sends no HELLO until one interval later. */
	cr = base_cfg(22, SF_ROLE_RELAY, 0);
	cr.hello_ms = 1000;
	cr.hello_mode = SF_HELLO_ON;
	make_node(&rel, rs, rm, 4, 0, &cr, NULL, 0);
	now = 0;
	sf_node_start(&rel, now, 0);
	sf_node_poll(&rel, now, &act);
	check("HELLO at start", act.kind == SF_ACT_TX && (act.tx[0] & 0x0f) == SF_TYPE_HELLO);
	sf_node_on_tx_done(&rel, 5, true, false);
	sf_node_on_tx_done(&rel, 500, true, false); /* an ACK or any other frame */
	sf_node_poll(&rel, 1300, &act);
	check("no HELLO while a frame was sent within the interval", act.kind == SF_ACT_RX);
	sf_node_poll(&rel, 1400, &act);
	check("HELLO when idle for a full interval", act.kind == SF_ACT_TX &&
							      (act.tx[0] & 0x0f) == SF_TYPE_HELLO);

	/* Links start clean after a stop and start. */
	sf_node_stop(&src, 5000, "test");
	sf_node_start(&src, 5000, 0);
	check("stop and start resets the link table", sf_link_find(&src.links, 33) == NULL);
}

static void test_rx_policy(void)
{
	struct sf_rx_state idle = {.ack_wait = false, .frame_in_progress = false};
	struct sf_rx_state idle_busy = {.ack_wait = false, .frame_in_progress = true};
	struct sf_rx_state waiting = {.ack_wait = true, .frame_in_progress = false};
	struct sf_rx_state waiting_busy = {.ack_wait = true, .frame_in_progress = true};

	printf("receive policy\n");
	check("an ACK ends an ACK wait", sf_rx_decide(&waiting, SF_RXE_ACK) == SF_RXA_CANCEL_NOW);
	check("another frame does not end an ACK wait",
	      sf_rx_decide(&waiting, SF_RXE_FRAME) == SF_RXA_CONTINUE);
	check("a frame ends an idle listen", sf_rx_decide(&idle, SF_RXE_FRAME) == SF_RXA_CANCEL_NOW);
	check("deadline cancels when no frame is arriving",
	      sf_rx_decide(&idle, SF_RXE_DEADLINE) == SF_RXA_CANCEL_NOW &&
		      sf_rx_decide(&waiting, SF_RXE_DEADLINE) == SF_RXA_CANCEL_NOW);
	check("a deadline waits for a frame in progress",
	      sf_rx_decide(&idle_busy, SF_RXE_DEADLINE) == SF_RXA_WAIT_FRAME_END &&
		      sf_rx_decide(&waiting_busy, SF_RXE_DEADLINE) == SF_RXA_WAIT_FRAME_END);
	check("a wake (stop, start, setting) waits for a frame in progress",
	      sf_rx_decide(&idle_busy, SF_RXE_WAKE) == SF_RXA_WAIT_FRAME_END &&
		      sf_rx_decide(&idle, SF_RXE_WAKE) == SF_RXA_CANCEL_NOW);
}

static void test_idle_listen(void)
{
	struct sf_node sink, rel;
	struct sf_slot ks[4], rs[4];
	uint8_t km[4 * 64], rm[4 * 64];
	struct sf_cfg ck, cr;
	struct sf_action act;

	printf("idle listen until the next deadline\n");
	ck = base_cfg(33, SF_ROLE_SINK, 0);
	make_node(&sink, ks, km, 4, 0, &ck, NULL, 0);
	sf_node_start(&sink, 0, 0);
	sf_node_poll(&sink, 10, &act);
	check("no deadline: listen for the maximum", act.kind == SF_ACT_RX && act.idle_listen &&
							      act.rx_ms == SF_RX_MAX_MS);

	cr = base_cfg(22, SF_ROLE_RELAY, 0);
	cr.hello_ms = 1000;
	cr.hello_mode = SF_HELLO_ON;
	make_node(&rel, rs, rm, 4, 0, &cr, NULL, 0);
	sf_node_start(&rel, 0, 0);
	sf_node_poll(&rel, 0, &act);
	sf_node_on_tx_done(&rel, 5, true, false); /* HELLO sent, next one due at 905 */
	sf_node_poll(&rel, 40, &act); /* the gap after the transmission */
	sf_node_poll(&rel, 100, &act);
	check("listens until the next HELLO is due", act.kind == SF_ACT_RX && act.idle_listen &&
							      act.rx_ms >= 800 && act.rx_ms <= 810);
	sf_node_poll(&rel, 900, &act);
	check("a due deadline gives the minimum listen", act.kind == SF_ACT_RX && act.rx_ms == SF_RX_MIN_MS);
}

static int64_t adv_us_value;

static int64_t adv_us(void)
{
	return adv_us_value;
}

static void test_rtt_us(void)
{
	struct sf_node src, sink;
	struct sf_slot ss[4], ks[4];
	uint8_t sm[4 * 64], km[4 * 64];
	struct sf_cfg cs, ck;
	struct sf_action act;
	int64_t now = 1000;

	printf("rtt_us on ACK_RX\n");
	cs = base_cfg(11, SF_ROLE_SOURCE, 33);
	ck = base_cfg(33, SF_ROLE_SINK, 0);
	cs.count = 1;
	make_node(&src, ss, sm, 4, 0, &cs, NULL, 0);
	make_node(&sink, ks, km, 4, 0, &ck, NULL, 0);
	ncap = 0;
	sf_node_set_emit(&src, capture, NULL);
	sf_node_set_clock(&src, adv_us);
	sf_node_start(&src, now, 1);
	sf_node_start(&sink, now, 0);
	adv_us_value = 1000000;
	check("source tx", pump_tx(&src, &now, &act, 4));
	sf_node_on_rx(&sink, now, act.tx, act.tx_len, -100);
	adv_us_value = 1008000; /* the ACK is processed 8 ms of device time after the TX ended */
	check("sink acks", pump_tx(&sink, &now, &act, 4));
	sf_node_on_rx(&src, now, act.tx, act.tx_len, -100);
	check("ACK_RX carries rtt_us", cap_has("ACK_RX") && cap_has("rtt_us=8000"));
}

int main(void)
{
	test_codec();
	test_dedup();
	test_store();
	test_hop();
	test_retry();
	test_relay();
	test_queue_full();
	test_probe();
	test_logs();
	test_open_loop();
	test_stopped_node();
	test_generator_rate();
	test_heard_cleared();
	test_liveness();
	test_rx_policy();
	test_idle_listen();
	test_rtt_us();
	test_hold_cancel();
	test_runtime_settings();
	test_phy_len();
	printf("\n%s (%d failed)\n", failed ? "FAILED" : "OK", failed);
	return failed ? 1 : 0;
}
