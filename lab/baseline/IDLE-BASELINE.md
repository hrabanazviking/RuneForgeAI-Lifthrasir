# Lifthrasir idle baseline report v0.1 (LIF-0206)

Scope: fixture/recorded-data baseline produced offline by lab/baseline_report.py. This is NOT a measurement of a running production observer; no production observer exists yet.
Method: CPU busy/idle from two /proc/stat aggregate snapshots; memory from one /proc/meminfo snapshot; pressure from PSI some/full lines. Any value absent from the input is reported as unmeasured, never estimated.

## Inputs (provenance)
- input_file: pressure_cpu.txt sha256=8e7063c4ffbcb18572ff1aa8c5e918fda58051e2544713189815ba15382dc83f
- input_file: pressure_io.txt sha256=16f4b308b29df56c6c28276f3b8b043ab30e0750129787d0c7168b7244030612
- input_file: pressure_memory.txt sha256=fbdba056b572c46ba0271b1486833b16c2a7a5b571065ba38af50f76a4d6cc3e
- input_file: proc_meminfo.txt sha256=b9862ab1542a344aac05fa940d4517fd5fba4fa9abfc220d52f782b7c45f2e2e
- input_file: proc_stat_t1.txt sha256=7086393ca2782a12c909fc189b74cbb3fd505748d6ed66cafb0968f5594dc0c0
- input_file: proc_stat_t2.txt sha256=d3ab09e485a8458f0e55bbbeec003ec289bc5cc6eafc531c6798ab156d0f69c4
- sample_counts: proc_stat_snapshots=2 meminfo_snapshots=1 pressure_files=3

## CPU (idle overhead)
- cpu_busy_percent: 20 (derived: proc_stat_t1.txt:cpu + proc_stat_t2.txt:cpu; formula: 100*(dtotal-didle_all)/dtotal)
- cpu_idle_percent: 80 (derived: 100 - cpu_busy_percent)

## Memory
- mem_total_kb: 16384000 (source: proc_meminfo.txt:MemTotal)
- mem_free_kb: 8192000 (source: proc_meminfo.txt:MemFree)
- mem_available_kb: 12288000 (source: proc_meminfo.txt:MemAvailable)
- buffers_kb: 512000 (source: proc_meminfo.txt:Buffers)
- cached_kb: 4096000 (source: proc_meminfo.txt:Cached)
- swap_total_kb: 4194304 (source: proc_meminfo.txt:SwapTotal)
- swap_free_kb: 4194304 (source: proc_meminfo.txt:SwapFree)
- mem_available_percent: 75 (derived: proc_meminfo.txt:MemAvailable / proc_meminfo.txt:MemTotal * 100)

## Pressure (PSI)
- pressure_cpu_some_avg10: 1.5 (source: pressure_cpu.txt:some avg10)
- pressure_cpu_some_avg60: 0.5 (source: pressure_cpu.txt:some avg60)
- pressure_cpu_some_avg300: 0.1 (source: pressure_cpu.txt:some avg300)
- pressure_cpu_some_total_us: 1234567 (source: pressure_cpu.txt:some total)
- pressure_cpu_full_avg10: 0 (source: pressure_cpu.txt:full avg10)
- pressure_cpu_full_avg60: 0 (source: pressure_cpu.txt:full avg60)
- pressure_cpu_full_avg300: 0 (source: pressure_cpu.txt:full avg300)
- pressure_cpu_full_total_us: 0 (source: pressure_cpu.txt:full total)
- pressure_memory_some_avg10: 2.25 (source: pressure_memory.txt:some avg10)
- pressure_memory_some_avg60: 1 (source: pressure_memory.txt:some avg60)
- pressure_memory_some_avg300: 0.25 (source: pressure_memory.txt:some avg300)
- pressure_memory_some_total_us: 7654321 (source: pressure_memory.txt:some total)
- pressure_memory_full_avg10: 1.75 (source: pressure_memory.txt:full avg10)
- pressure_memory_full_avg60: 0.75 (source: pressure_memory.txt:full avg60)
- pressure_memory_full_avg300: 0.2 (source: pressure_memory.txt:full avg300)
- pressure_memory_full_total_us: 5432109 (source: pressure_memory.txt:full total)
- pressure_io_some_avg10: 0.5 (source: pressure_io.txt:some avg10)
- pressure_io_some_avg60: 0.25 (source: pressure_io.txt:some avg60)
- pressure_io_some_avg300: 0.05 (source: pressure_io.txt:some avg300)
- pressure_io_some_total_us: 2222222 (source: pressure_io.txt:some total)
- pressure_io_full_avg10: 0.25 (source: pressure_io.txt:full avg10)
- pressure_io_full_avg60: 0.1 (source: pressure_io.txt:full avg60)
- pressure_io_full_avg300: 0.02 (source: pressure_io.txt:full avg300)
- pressure_io_full_total_us: 1111111 (source: pressure_io.txt:full total)

## Limitations
- Fixture-based baseline only; a live idle measurement of a real observer is future work and is NOT claimed here.
- Evidence status: reproducer-level, fixture-tested offline on purpleraider only. Not lab-verified, cross-platform-verified or human-reviewed.
