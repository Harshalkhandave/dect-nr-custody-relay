# Serial logger

`serial_logger.py` reads the console of one board and writes it to the terminal and to a text file at the same time. By default you can also type shell commands (`exp status`, `exp start` and so on) in the same window.

## Setup

You need Python 3.10 or newer and `pyserial`:

```
python -m pip install -r requirements.txt
```

## Use

```
# list the serial ports
python serial_logger.py --list

# open an interactive session on COM9
python serial_logger.py COM9

# write the log to a file of your choice
python serial_logger.py COM9 --out my_run.txt

# only record, without typing
python serial_logger.py COM9 --no-interact
```

## Time stamps

Every logged line starts with the host's clock (`HH:MM:SS.mmm`). A command you type is recorded as `>>> <command>`. The board's own clock is inside the line (`time=` in ms and `time_us=` in microseconds).

## Good to know

- Only one program can use a COM port at a time on Windows, so close other serial terminals first.
- Use `exp sett size 16`. Payloads of 48 and 64 bytes are padded by the PHY slot and rejected.
- The sweep driver `tools/run_sweep.py` uses the harness in `tools/harness/` and does not need this logger. The logger is for working by hand.
