# Frame format

A frame is the payload of one DECT NR+ PHY packet. The modem adds its own PHY header around it, and that header is not counted in the sizes below. All fields of more than one byte are little-endian. The code is in `src/sf_codec.c` and `src/sf_types.h`.

## The 18-byte header

Every frame starts with the same header.

| Byte | Size | Field | Meaning |
|---|---|---|---|
| 0 | 1 | version and type | version 1 in the high four bits, frame type in the low four bits |
| 1 | 1 | flags | see below |
| 2 | 2 | `src` | node that created the frame |
| 4 | 2 | `dst` | node the frame is meant for |
| 6 | 2 | `prev` | node that sent this hop |
| 8 | 2 | `next` | node this hop is addressed to |
| 10 | 2 | `seq` | 16-bit sequence number, counted per source and class |
| 12 | 2 | `epoch` | boot counter of the node that created the frame |
| 14 | 1 | `hops` | hops taken so far |
| 15 | 1 | `ttl` | hops still allowed |
| 16 | 2 | `payload_len` | payload length in bytes |

Frame types: 1 = DATA, 2 = HELLO, 3 = ACK, 4 = PROBE.

Flags: bit 0 marks custody (set on every DATA frame), bit 1 marks a retransmission, bits 2 and 3 hold the class (0 = telemetry, 1 = alarm), and bit 4 marks a secured frame. A frame with bit 4 set is rejected.

## What follows the header

| Type | Total size | Extra content |
|---|---|---|
| DATA | 18 + payload | the payload starts at byte 18. In the measurements the payload is 16 bytes, so a frame is 34 bytes |
| HELLO | 20 | byte 18: sender role (0 source, 1 relay, 2 sink). Byte 19: free space in the sender's store in percent. `dst` and `next` are 0xFFFF, which means everyone |
| ACK | 23 | byte 18: status. Bytes 19 and 20: free slots for this class. Bytes 21 and 22: the sender's boot counter |
| PROBE | 18 | nothing. `dst` and `next` are the neighbour being probed, `ttl` is 1 and `seq` is a probe counter |

An ACK copies `src`, `dst`, `seq`, `epoch` and the class from the frame it answers. Its `prev` is the node sending the ACK and its `next` is the node that sent the frame.

ACK status values: 0x00 accepted, 0x01 duplicate, 0x02 queue full, 0x03 TTL expired, 0x04 no route, 0x10 probe reply.

## Length on the air

The firmware writes the packet length into the PHY header, counted in subslots (one subslot is 208.33 microseconds). DATA frames of up to 32 bytes use 4 subslots, frames of 33 to 64 bytes use 8 subslots and larger ones use 16. HELLO, ACK and PROBE frames use at least the `ctrl_subslots` setting, which is 8 by default. So a 34-byte DATA frame takes 8 subslots, about 1.67 ms. The rule is in `src/sf_phy.h`.
