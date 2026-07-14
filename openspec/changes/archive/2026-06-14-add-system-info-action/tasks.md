## 1. Action Handler

- [x] 1.1 Add `_read_system_vitals()` helper in `actions.py` that reads CPU temp (glob `/sys/class/thermal/thermal_zone*/temp`, take max), load avg (`/proc/loadavg` first field), free memory (`/proc/meminfo` MemAvailable), and uptime (`/proc/uptime` first field); returns a dict; handles missing files gracefully
- [x] 1.2 Add `_format_system_info_italian(vitals)` that converts the dict to a single natural Italian sentence (integer °C, one-decimal load, integer GB memory, two-unit uptime)
- [x] 1.3 Register `@registry.register("system_info")` handler that calls both helpers and speaks the result via `asyncio.to_thread(get_engine().say, text, "it-IT")`

## 2. Example Trigger

- [x] 2.1 Add commented-out `system_info` example trigger to `conf/actions/user.yaml` with phrase `"come sta il sistema"` and example patterns (`"come * sistema"`, `"stato * sistema"`, `"temperatura"`)
