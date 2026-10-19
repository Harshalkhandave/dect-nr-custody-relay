# Tests that run on a PC

`firmware/tests/host_test.c` tests the part of the firmware that does not need hardware: the protocol code, the store, the duplicate detection, the link states and the frame codec. It needs a C compiler and nothing else (no board, no Zephyr, no modem).

From the folder `firmware/tests`:

```
gcc -std=c11 -Wall -Wextra -Werror -DSF_HOST -I../src -o host_test host_test.c \
    ../src/sf_codec.c ../src/sf_dedup.c ../src/sf_store.c ../src/sf_link.c ../src/sf_node.c
./host_test
```

The `SF_HOST` define makes `../src/sf_types.h` use fixed array sizes instead of the Kconfig values.

The tests cover: encoding and decoding of frames, duplicate suppression, the store, a frame over one hop and over a relay, retries and backoff, the "queue full" answer, probing and the link states, the hold-down and its early end, open-loop mode, a stopped node, the log lines, the source's frame rate, runtime settings, the PHY length rule, liveness, the receive policy and the ACK round-trip time stamps.
