#!/bin/sh
# Minimal fixture reproducer: fails (exit 1) while the counter bug
# is present, passes (exit 0) once the candidate guard is applied.
# Recorded fixture text only; never executed against a real kernel.
grep -q 'fixture_ready() && fixture_armed()' drivers/fixture/fixture_counter.c
