# How the tests were run

This page describes the setup of the measurements and the exact steps of a run. All commands are typed into the `exp` shell of a board (115200 baud, 8N1). Each board has its own node id, which `exp status` prints as `node=<id>`. Below, `<SINK>`, `<RELAY>` and `<SOURCE>` stand for those ids.

## The setup

Three Conexio Stratus Pro boards (source, relay, sink) stood in a line on the floor of one room, with their flexible antennas lying flat. The source was about 0.5 m from the relay, the relay about 2 m from the sink, and the source about 2.5 m from the sink. These distances are estimates (`data/SETUP.json`). One shelf stood between the source and the relay, and the same shelf was between the source and the sink. Nothing was moved during the runs.

The source used TX power index 1, and the relay and the sink used index 10. The lower power keeps the sink from hearing the source directly, so every frame has to go through the relay.

A host computer controlled the boards through their shell and logged their consoles. The source and the relay were reached through a TCP-to-serial bridge on a separate computer, and the sink through a local COM port.

## Running the whole sweep

`tools/run_sweep.py` runs the full schedule. Inside each repetition the conditions come in a random order that is drawn from a fixed seed, every board is rebooted before each run, and every run gets its own folder. You must give the three serial ports with `--sink`, `--relay` and `--source` (for example `COM7` or `socket://HOST:7777`). `python tools/run_sweep.py --help` shows all options.

The driver can run more conditions than the paper reports. The paper uses custody and open-loop at outage lengths of 5, 15, 30, 60 and 330 s, ten runs each.

## One run by hand

### 1. Set the roles and settings

```
sink:    exp role sink
relay:   exp role relay
source:  exp role source

sink and relay:   exp sett hello 2000
                  exp sett hello_tx on
                  exp sett direct on
relay:            exp sett assume_up off
                  exp sett ack_timeout 200
source:           exp sett direct off
                  exp sett dest <SINK>
                  exp route set <SINK> <RELAY>
                  exp sett size 16
                  exp sett interval 1000
                  exp sett count 0
                  exp sett assume_up off
                  exp sett ack_timeout 400
                  exp sett policy reject
all three:        exp sett custody on        (off for the open-loop baseline)
                  exp sett mcs 0
                  exp sett rx_slice 15
                  exp sett power 10          (on the source: exp sett power 1)
gaps:             relay: exp sett gap 5      source: exp sett gap 35      (the sink keeps 20)
```

Each run folder stores the settings that were in force (`config_source.txt`, `config_relay.txt`, `config_sink.txt`). `exp sett` lists every key, and [`../firmware/docs/SETTINGS_REFERENCE.md`](../firmware/docs/SETTINGS_REFERENCE.md) explains them.

### 2. Start the nodes

```
sink:    exp start
relay:   exp start
source:  exp start <N>        N = D + 120 frames, one per second
```

Start the sink first, then the relay, then the source. D is the outage length in seconds.

### 3. Create the outage

Thirty seconds after the source started:

```
sink:    exp stop
```

D seconds later:

```
sink:    exp start
```

A stopped node neither receives nor sends. The source stops by itself after N frames, once its store is empty.

### 4. Read the counters

`exp status` on each board prints the counters (generated, delivered, stored, drained, retries and more). The sink's delivered counter starts from zero again when the sink is started after the outage. The delivered total of a run is therefore the counter printed at the stop plus the counter at the end. The analysis does this for you.

### 5. Between runs

Run `exp reboot` on every board.

## Analysing the runs

Run `python tools/analysis/e1_analyze.py --root data/E1_outage_sweep_v2`. See [`READING_THE_RESULTS.md`](READING_THE_RESULTS.md) for what it produces.
