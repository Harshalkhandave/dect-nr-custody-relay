# Link state

Every node keeps one link per next hop. The source has a link to the relay, and the relay has a link to the sink. A link is in one of three states, and the code is in `src/sf_link.c`.

```
                 three probe replies in a row
      PROBING ---------------------------------> UP
        ^  |                                       |
        |  | a probe fails                         | four failed sends of a frame,
        |  | (the hold-down doubles)               | or 7 s of silence from the neighbour
        |  v                                       v
        +-- DOWN <---------------------------------+
   hold-down is over and the probe timer has run out,
   or a frame was heard, or a silent neighbour came back
```

- **UP.** The link works. Stored frames are sent one at a time, alarms first and then the oldest.
- **DOWN.** The link failed. The node sends no data and no probes on it. HELLO frames and ACKs for other nodes still go out. New frames wait in the store.
- **PROBING.** The node sends small PROBE frames to find out whether the neighbour answers again. Data stays in the store.

## How the state changes

| Change | When | Reason in the log |
|---|---|---|
| UP to DOWN | four sends of one frame got no ACK. The frame stays in the store | `max_attempts` |
| UP to DOWN | nothing was heard for 7 s from a neighbour that was heard before (`hello_dead`) | `hello_dead` |
| DOWN to PROBING | the hold-down is over and the probe timer (3 s, `t_probe`) has run out | `t_probe` |
| DOWN to PROBING | the hold-down is over and any frame from the neighbour was heard while DOWN | `hello` |
| DOWN to PROBING | a frame is heard after the neighbour was silent for 3 s or more (`hold_cancel`). This ends the hold-down at once | `returned` |
| PROBING to UP | three probe replies in a row (`n_up`), sent 200 ms apart (`probe_fast`) | `probes` |
| PROBING to DOWN | a probe fails (four sends without a reply) | `max_attempts` |
| any state to PROBING | the neighbour's boot counter changed, so it rebooted | `neighbor_reset` |

## The hold-down

After a failure the link waits before it probes. The first wait is 5 s (`hold_min`). Each failure in a row doubles it (5, 10, 20, 40 s) up to 60 s (`hold_max`). If a failure happens after the link has been UP for at least 60 s (`hold_reset`), the wait starts at 5 s again.

The hold-down protects a link that keeps failing. A neighbour that was only gone for a while and is then heard again does not have to wait it out: that is the case marked `returned` above.

## What counts as a sign of life

By default every frame from a neighbour counts, including frames addressed to other nodes (`liveness any`). HELLO frames are sent about every 2 s, with a little random jitter. A node skips a HELLO if it has sent another frame in the meantime.
