/*
 * Copyright (c) 2026 Conexio Technologies, Inc
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Modem bring-up and the half-duplex radio thread.
 * Protocol decisions live in sf_node.c. This file only moves frames.
 */

#include "sf_phy.h"
#include "sf_port.h"
#include "sf_rxpolicy.h"

#include <string.h>

#include <zephyr/drivers/hwinfo.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/version.h>
#include <modem/nrf_modem_lib.h>
#include <nrf_modem_at.h>
#include <nrf_modem_dect_phy.h>
#include <ncs_version.h>

LOG_MODULE_DECLARE(app, CONFIG_SF_LOG_LEVEL);

#define TX_HANDLE 0u
#define RX_HANDLE 1u

static bool phy_fatal;
static uint64_t modem_time;
/* Written by the modem callback immediately before it gives op_sem. */
static volatile int op_result;

struct phy_ctrl_field_common {
	uint32_t packet_length : 4;
	uint32_t packet_length_type : 1;
	uint32_t header_format : 3;
	uint32_t short_network_id : 8;
	uint32_t transmitter_id_hi : 8;
	uint32_t transmitter_id_lo : 8;
	uint32_t df_mcs : 3;
	uint32_t reserved : 1;
	uint32_t transmit_power : 4;
	uint32_t pad : 24;
};

K_SEM_DEFINE(op_sem, 0, 4);
/* Given from the modem callback when an ACK frame is decoded (runtime cancel_ack). */
K_SEM_DEFINE(ack_sem, 0, 1);
/* Event-driven idle listening (runtime rx_mode): a frame was queued, and a shell
 * command changed something the radio thread should look at.
 */
K_SEM_DEFINE(frame_sem, 0, 1);
K_SEM_DEFINE(wake_sem, 0, 1);
/* A frame start was seen (PCC) and its end (PDC or an error) was not. The longest frame is
 * 16 subslots, about 3.3 ms, so a start older than RX_FRAME_MAX_MS is treated as over.
 */
#define RX_FRAME_MAX_MS 5
#define RX_GUARD_MS     25
static atomic_t frame_busy;
static volatile int64_t frame_end_ms;

void radio_wake(void)
{
	k_sem_give(&wake_sem);
}

static void sem_give(void)
{
	(void)k_sem_give(&op_sem);
}

static void on_init(const struct nrf_modem_dect_phy_init_event *evt)
{
	if (evt->err) {
		LOG_ERR("phy init %d", evt->err);
		phy_fatal = true;
	}
	sem_give();
}

static void on_deinit(const struct nrf_modem_dect_phy_deinit_event *evt)
{
	ARG_UNUSED(evt);
	sem_give();
}

static void on_activate(const struct nrf_modem_dect_phy_activate_event *evt)
{
	if (evt->err) {
		LOG_ERR("phy activate %d", evt->err);
		phy_fatal = true;
	}
	sem_give();
}

static void on_deactivate(const struct nrf_modem_dect_phy_deactivate_event *evt)
{
	ARG_UNUSED(evt);
	sem_give();
}

static void on_configure(const struct nrf_modem_dect_phy_configure_event *evt)
{
	if (evt->err) {
		LOG_ERR("phy configure %d", evt->err);
		phy_fatal = true;
	}
	sem_give();
}

static bool op_succeeded(int err)
{
	return err == NRF_MODEM_DECT_PHY_SUCCESS || err == NRF_MODEM_DECT_PHY_OK_WITH_HARQ_RESET;
}

static void on_op_complete(const struct nrf_modem_dect_phy_op_complete_event *evt)
{
	op_result = (int)evt->err;
	if (!op_succeeded(op_result)) {
		LOG_WRN("phy op handle %u err %d", evt->handle, op_result);
	}
	sem_give();
}

static void on_cancel(const struct nrf_modem_dect_phy_cancel_event *evt)
{
	/* nrf_modem_dect_phy_cancel() sends this event and also one COMPLETED event for the
	 * cancelled operation. Only COMPLETED gives op_sem, so each operation yields exactly
	 * one token whether or not it was cancelled.
	 */
	ARG_UNUSED(evt);
}

static void on_pdc(const struct nrf_modem_dect_phy_pdc_event *evt)
{
	const uint8_t *data = evt->data;

	sf_port_on_pdc(data, evt->len, (int16_t)evt->rssi_2);
	atomic_clear(&frame_busy);
	/* Signal after the frame is queued so the radio thread finds it on wake-up. */
	k_sem_give(&frame_sem);
	if (sf_port_cancel_ack() && evt->len > 0 && (data[0] & 0x0fu) == SF_TYPE_ACK) {
		k_sem_give(&ack_sem);
	}
}

static void dect_phy_event_handler(const struct nrf_modem_dect_phy_event *evt)
{
	modem_time = evt->time;
	switch (evt->id) {
	case NRF_MODEM_DECT_PHY_EVT_INIT:
		on_init(&evt->init);
		break;
	case NRF_MODEM_DECT_PHY_EVT_DEINIT:
		on_deinit(&evt->deinit);
		break;
	case NRF_MODEM_DECT_PHY_EVT_ACTIVATE:
		on_activate(&evt->activate);
		break;
	case NRF_MODEM_DECT_PHY_EVT_DEACTIVATE:
		on_deactivate(&evt->deactivate);
		break;
	case NRF_MODEM_DECT_PHY_EVT_CONFIGURE:
		on_configure(&evt->configure);
		break;
	case NRF_MODEM_DECT_PHY_EVT_COMPLETED:
		on_op_complete(&evt->op_complete);
		break;
	case NRF_MODEM_DECT_PHY_EVT_CANCELED:
		on_cancel(&evt->cancel);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PDC:
		on_pdc(&evt->pdc);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PDC_ERROR:
	case NRF_MODEM_DECT_PHY_EVT_PCC_ERROR:
		atomic_clear(&frame_busy);
		LOG_DBG("phy crc error t=%" PRIu64, modem_time);
		break;
	case NRF_MODEM_DECT_PHY_EVT_PCC:
		frame_end_ms = k_uptime_get() + RX_FRAME_MAX_MS;
		atomic_set(&frame_busy, 1);
		break;
	case NRF_MODEM_DECT_PHY_EVT_RSSI:
	case NRF_MODEM_DECT_PHY_EVT_RADIO_CONFIG:
	case NRF_MODEM_DECT_PHY_EVT_TIME:
	case NRF_MODEM_DECT_PHY_EVT_CAPABILITY:
	case NRF_MODEM_DECT_PHY_EVT_BANDS:
	case NRF_MODEM_DECT_PHY_EVT_LATENCY:
	case NRF_MODEM_DECT_PHY_EVT_LINK_CONFIG:
	case NRF_MODEM_DECT_PHY_EVT_STF_CONFIG:
	case NRF_MODEM_DECT_PHY_EVT_TEST_RF_TX_CW_CONTROL_CONFIG:
	default:
		break;
	}
}

static int transmit(struct phy_ctrl_field_common *header, const uint8_t *data, uint16_t len,
		   uint8_t power, uint8_t mcs)
{
	struct nrf_modem_dect_phy_tx_params tx;

	memset(header, 0, sizeof(*header));
	header->header_format = 0x0;
	header->packet_length_type = 0x0;
	header->packet_length = sf_phy_len_code(len > 0 ? (data[0] & 0x0fu) : 0, len, sf_port_ctrl_subslots());
	header->short_network_id = (CONFIG_NETWORK_ID & 0xff);
	header->transmitter_id_hi = (uint8_t)(sf_port_node_id() >> 8);
	header->transmitter_id_lo = (uint8_t)(sf_port_node_id() & 0xff);
	header->transmit_power = power;
	header->df_mcs = mcs;

	memset(&tx, 0, sizeof(tx));
	tx.start_time = 0;
	tx.handle = TX_HANDLE;
	tx.network_id = CONFIG_NETWORK_ID;
	tx.phy_type = 0;
	tx.lbt_rssi_threshold_max = 0;
	tx.carrier = CONFIG_CARRIER;
	tx.lbt_period = NRF_MODEM_DECT_LBT_PERIOD_MAX;
	tx.phy_header = (union nrf_modem_dect_phy_hdr *)header;
	tx.data = (uint8_t *)data;
	tx.data_size = len;
	return nrf_modem_dect_phy_tx(&tx);
}

static int receive(uint32_t duration_ms)
{
	struct nrf_modem_dect_phy_rx_params rx = {
		.start_time = 0,
		.handle = RX_HANDLE,
		.network_id = CONFIG_NETWORK_ID,
		.mode = NRF_MODEM_DECT_PHY_RX_MODE_CONTINUOUS,
		.rssi_interval = NRF_MODEM_DECT_PHY_RSSI_INTERVAL_OFF,
		.link_id = NRF_MODEM_DECT_PHY_LINK_UNSPECIFIED,
		.rssi_level = sf_port_rssi_level(),
		.carrier = CONFIG_CARRIER,
		.duration = duration_ms * NRF_MODEM_DECT_MODEM_TIME_TICK_RATE_KHZ,
		.filter.short_network_id = CONFIG_NETWORK_ID & 0xff,
		.filter.is_short_network_id_used = 1,
		.filter.receiver_identity = CONFIG_SF_RX_FILTER_ID,
	};

	return nrf_modem_dect_phy_rx(&rx);
}

static int wait_boot(void)
{
	k_sem_take(&op_sem, K_FOREVER);
	return phy_fatal ? -EIO : 0;
}

static int wait_op(uint32_t handle)
{
	int rc = k_sem_take(&op_sem, K_MSEC(CONFIG_SF_OP_TIMEOUT_MS));
	int result;

	if (rc != 0) {
		LOG_ERR("modem operation %u timed out", handle);
		(void)nrf_modem_dect_phy_cancel(handle);
		(void)k_sem_take(&op_sem, K_MSEC(500));
		while (k_sem_take(&op_sem, K_NO_WAIT) == 0) {
		}
		return -ETIMEDOUT;
	}
	result = op_result;
	while (k_sem_take(&op_sem, K_NO_WAIT) == 0) {
	}
	if (op_succeeded(result)) {
		return 0;
	}
	LOG_WRN("modem operation %u finished err %d", handle, result);
	return -EIO;
}

/*
 * Wait for the RX operation, but end it early when an ACK frame was received.
 * The frame is already in the RX queue (the modem delivers the PDC before we are
 * woken), so cancelling loses nothing; the node re-arms the rest of its window.
 */
static int wait_rx_or_ack(void)
{
	struct k_poll_event ev[2] = {
		K_POLL_EVENT_STATIC_INITIALIZER(K_POLL_TYPE_SEM_AVAILABLE, K_POLL_MODE_NOTIFY_ONLY,
						&op_sem, 0),
		K_POLL_EVENT_STATIC_INITIALIZER(K_POLL_TYPE_SEM_AVAILABLE, K_POLL_MODE_NOTIFY_ONLY,
						&ack_sem, 0),
	};
	int rc = k_poll(ev, 2, K_MSEC(CONFIG_SF_OP_TIMEOUT_MS));

	if (rc != 0 || ev[0].state == K_POLL_STATE_SEM_AVAILABLE) {
		return wait_op(RX_HANDLE);
	}
	(void)k_sem_take(&ack_sem, K_NO_WAIT);
	(void)nrf_modem_dect_phy_cancel(RX_HANDLE);
	/* The cancelled RX operation reports COMPLETED once; its result is not needed. */
	if (k_sem_take(&op_sem, K_MSEC(500)) != 0) {
		LOG_ERR("rx cancel timed out");
		return -ETIMEDOUT;
	}
	return 0;
}

/*
 * Idle listen (see sf_rxpolicy.h): one long
 * receive that this thread ends. The decision is sf_rx_decide() (host-tested). Returns 0 once
 * the receive operation is over; the caller then drains the frame queue.
 */
static int rx_idle_wait(uint32_t listen_ms)
{
	int64_t end = k_uptime_get() + (int64_t)listen_ms;
	struct k_poll_event ev[3];
	struct sf_rx_state st = {.ack_wait = false, .frame_in_progress = false};

	while (true) {
		int64_t left = end - k_uptime_get();
		enum sf_rx_event e;
		int rc;

		k_poll_event_init(&ev[0], K_POLL_TYPE_SEM_AVAILABLE, K_POLL_MODE_NOTIFY_ONLY, &op_sem);
		k_poll_event_init(&ev[1], K_POLL_TYPE_SEM_AVAILABLE, K_POLL_MODE_NOTIFY_ONLY, &frame_sem);
		k_poll_event_init(&ev[2], K_POLL_TYPE_SEM_AVAILABLE, K_POLL_MODE_NOTIFY_ONLY, &wake_sem);
		rc = k_poll(ev, 3, K_MSEC(left > 0 ? left : 0));
		if (rc == 0 && ev[0].state == K_POLL_STATE_SEM_AVAILABLE) {
			return wait_op(RX_HANDLE); /* the receive ended by itself */
		}
		if (rc != 0) {
			e = SF_RXE_DEADLINE;
		} else if (ev[1].state == K_POLL_STATE_SEM_AVAILABLE) {
			(void)k_sem_take(&frame_sem, K_NO_WAIT);
			e = SF_RXE_FRAME;
		} else {
			(void)k_sem_take(&wake_sem, K_NO_WAIT);
			e = SF_RXE_WAKE;
		}
		st.frame_in_progress = atomic_get(&frame_busy) != 0 && k_uptime_get() < frame_end_ms;
		switch (sf_rx_decide(&st, e)) {
		case SF_RXA_CONTINUE:
			continue;
		case SF_RXA_WAIT_FRAME_END: {
			int64_t wait = frame_end_ms - k_uptime_get();

			if (wait > 0) {
				(void)k_sem_take(&frame_sem, K_MSEC(wait));
			}
			break;
		}
		case SF_RXA_CANCEL_NOW:
		default:
			break;
		}
		break;
	}
	(void)nrf_modem_dect_phy_cancel(RX_HANDLE);
	/* The cancelled receive reports COMPLETED once (as in wait_rx_or_ack). */
	if (k_sem_take(&op_sem, K_MSEC(500)) != 0) {
		LOG_ERR("rx cancel timed out");
		return -ETIMEDOUT;
	}
	return 0;
}

static void drain_sem(void)
{
	while (k_sem_take(&op_sem, K_NO_WAIT) == 0) {
	}
}

static void radio_thread(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	while (1) {
		sf_port_wait_until_started();
		while (sf_port_running()) {
			struct sf_action act;
			struct phy_ctrl_field_common header;
			uint8_t buf[CONFIG_SF_PHY_MTU];
			uint8_t power;
			uint8_t mcs;
			int err;

			sf_port_note_stable_if_due();
			sf_port_poll(&act);
			if (!sf_port_running()) {
				break;
			}
			if (act.kind == SF_ACT_TX) {
				if (act.tx_len == 0 || act.tx_len > sizeof(buf)) {
					sf_port_on_tx_done(false, act.inflight);
					continue;
				}
				memcpy(buf, act.tx, act.tx_len);
				sf_port_radio(&power, &mcs);
				drain_sem();
				err = transmit(&header, buf, act.tx_len, power, mcs);
				if (err != 0) {
					LOG_ERR("tx submit %d", err);
					sf_port_on_tx_done(false, act.inflight);
					continue;
				}
				err = wait_op(TX_HANDLE);
				if (err == -ETIMEDOUT) {
					sf_port_stop("modem_timeout");
					break;
				}
				/* LBT busy, bad header, or a rejected op: the frame did not
				 * leave the radio. Count the attempt and keep listening.
				 */
				sf_port_on_tx_done(err == 0, act.inflight);
			} else {
				uint32_t slice = act.rx_ms == 0 ? 1u : act.rx_ms;

				bool idle = act.idle_listen;

				drain_sem();
				k_sem_reset(&ack_sem);
				k_sem_reset(&frame_sem);
				/* An idle listen is ended by this thread, so the operation is made
				 * a little longer than the listen and never expires first.
				 */
				err = receive(idle ? slice + RX_GUARD_MS : slice);
				if (err != 0) {
					LOG_ERR("rx submit %d", err);
					sf_port_stop("rx_error");
					break;
				}
				if (idle) {
					err = rx_idle_wait(slice);
				} else if (sf_port_cancel_ack() && act.ack_wait) {
					err = wait_rx_or_ack();
				} else {
					err = wait_op(RX_HANDLE);
				}
				if (err == -ETIMEDOUT) {
					sf_port_stop("modem_timeout");
					break;
				}
				if (err != 0) {
					LOG_ERR("rx operation failed");
					sf_port_stop("rx_error");
					break;
				}
				sf_port_drain_rx();
			}
		}
	}
}

static K_THREAD_STACK_DEFINE(radio_stack, CONFIG_SF_RADIO_STACK);
static struct k_thread radio_thread_data;

static uint16_t read_device_id(void)
{
	uint16_t id = 0;

#if IS_ENABLED(CONFIG_SF_DEVICE_ID_OVERRIDE)
	id = (uint16_t)CONFIG_SF_DEVICE_ID;
#else
	if (hwinfo_get_device_id((uint8_t *)&id, sizeof(id)) < 0) {
		/* Every board would end up with the same id 1. */
		LOG_ERR("device id unavailable: set CONFIG_SF_DEVICE_ID_OVERRIDE");
		id = 0;
	}
#endif
	return id;
}

static int boot_phy(void)
{
	static const struct nrf_modem_dect_phy_config_params params = {
		.band_group_index = ((CONFIG_CARRIER >= 525 && CONFIG_CARRIER <= 551)) ? 1 : 0,
		.harq_rx_process_count = CONFIG_SF_HARQ_RX_PROCESSES,
		.harq_rx_expiry_time_us = CONFIG_SF_HARQ_RX_EXPIRY_US,
	};
	int err;

	err = nrf_modem_lib_init();
	if (err != 0) {
		LOG_ERR("modem lib %d", err);
		return err;
	}
	err = nrf_modem_dect_phy_event_handler_set(dect_phy_event_handler);
	if (err != 0) {
		LOG_ERR("phy handler %d", err);
		return err;
	}
	err = nrf_modem_dect_phy_init();
	if (err != 0 || wait_boot() != 0) {
		LOG_ERR("phy init failed");
		return err != 0 ? err : -EIO;
	}
	err = nrf_modem_dect_phy_configure(&params);
	if (err != 0 || wait_boot() != 0) {
		LOG_ERR("phy configure failed");
		return err != 0 ? err : -EIO;
	}
	err = nrf_modem_dect_phy_activate(NRF_MODEM_DECT_PHY_RADIO_MODE_LOW_LATENCY);
	if (err != 0 || wait_boot() != 0) {
		LOG_ERR("phy activate failed");
		return err != 0 ? err : -EIO;
	}
	return 0;
}

/*
 * One line of firmware identity and one of modem identity, so every raw log says what it ran on.
 * The AT queries are read-only. Static buffers keep them off the main stack.
 */
static void log_boot_info(void)
{
	static char fw[64];
	static char hw[64];
	static char uuid[48];
	int temp_c = 0;
	int vbat_mv = 0;

	LOG_INF("BOOT_INFO: fw=%s ncs=%s zephyr=%s main_stack=%d radio_stack=%d carrier=%d net=%d",
		SF_GIT_REV, NCS_VERSION_STRING, KERNEL_VERSION_STRING, CONFIG_MAIN_STACK_SIZE,
		CONFIG_SF_RADIO_STACK, CONFIG_CARRIER, CONFIG_NETWORK_ID);
	if (nrf_modem_at_scanf("AT+CGMR", "%63[^\r\n]", fw) <= 0) {
		strcpy(fw, "unknown");
	}
	if (nrf_modem_at_scanf("AT%HWVERSION", "%%HWVERSION: %63[^\r\n]", hw) <= 0) {
		strcpy(hw, "unknown");
	}
	if (nrf_modem_at_scanf("AT%XMODEMUUID", "%%XMODEMUUID: %47[^\r\n]", uuid) <= 0) {
		strcpy(uuid, "unknown");
	}
	if (nrf_modem_at_scanf("AT%XTEMP?", "%%XTEMP: %d", &temp_c) <= 0) {
		temp_c = -999;
	}
	if (nrf_modem_at_scanf("AT%XVBAT", "%%XVBAT: %d", &vbat_mv) <= 0) {
		vbat_mv = -1;
	}
	LOG_INF("BOOT_MODEM: fw=%s hw=%s uuid=%s temp_c=%d vbat_mv=%d", fw, hw, uuid, temp_c, vbat_mv);
}

int main(void)
{
	int err;

	sf_port_boot(read_device_id());
	err = boot_phy();
	if (err != 0) {
		return err;
	}
	log_boot_info();
	k_thread_create(&radio_thread_data, radio_stack, CONFIG_SF_RADIO_STACK, radio_thread, NULL,
			NULL, NULL, 5, 0, K_NO_WAIT);
	k_thread_name_set(&radio_thread_data, "sf_radio");
	LOG_INF("shell: exp status|sett|route|start|stop|sf|link|neigh|alarm|save|load");
	if (sf_port_autostart_ok()) {
		err = sf_port_start(0);
		if (err != 0) {
			LOG_WRN("autostart failed %d", err);
		}
	} else {
		LOG_INF("idle — exp start");
	}
	return 0;
}
