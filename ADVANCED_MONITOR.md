# CRAMC v1.1.1 — Advanced System Monitor

This release adds a live system-observation layer beside the existing RAM and
storage cleanup tools. It is deliberately independent from the cleanup engine.

## Features

- Live CPU, RAM, swap, disk capacity, disk I/O counters and network counters.
- Process inventory with PID, name, account, state, CPU, resident memory,
  memory percentage, thread count, start time and executable path.
- Search and sorting across process name, PID, owner, CPU and memory use.
- Bounded in-memory history with a CPU/RAM/disk trend chart.
- Advisory warnings for high CPU, memory, swap and disk usage.
- JSON system reports and CSV process exports, written atomically.
- Confirmed graceful process exit for same-user processes only.

## Safety

The monitor never terminates a process automatically. PID 1 and the CRAMC
process are protected. Processes owned by another account and a conservative
set of critical operating-system process names are rejected. A selected
process receives a graceful termination request only after a confirmation
prompt. CRAMC never escalates to a forced kill if the process does not exit.

## Metric notes

Disk capacity refers to the system volume (or / on Linux). Disk I/O and network
values are cumulative byte counters since boot, not transfer rates. CPU values
may be near zero on the first sample because the operating system needs a
baseline. The history is bounded and held in memory; it is cleared at exit.

Health findings are advisory, not a hardware diagnostic. Available memory and
file cache are not treated as inherently wasteful. No optimization action is
triggered by a warning.

## Privacy and reports

JSON includes the latest system sample, health findings, process metadata and
bounded history. CSV contains process rows only. Command-line arguments,
environment variables, file contents and passwords are deliberately omitted.
The user chooses the destination and can inspect a report before sharing it.

## Tests

Run `python -m unittest discover -s tests -v` for the advanced monitor suite,
then `python cramc.py --selftest` and `python cramc.py --uitest` for the
application engine and desktop-language checks.
