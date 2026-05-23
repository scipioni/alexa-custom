# make-report prompt

Use this prompt in Claude Code to capture a new resource snapshot and compare it against previous ones.

---

## Prompt (paste into Claude Code)

```
Take a resource snapshot of the running alexa-custom process and compare it with all previous snapshots in reports/.

Steps:
1. Find the alexa-client process: `ps aux | grep alexa-client | grep -v grep`
2. For that PID, collect:
   - CPU% and elapsed uptime: `ps -p <PID> -o %cpu,%mem,rss,vsz,etime,stat`
   - Memory detail: `cat /proc/<PID>/status | grep -E 'VmRSS|VmSize|VmPeak|VmSwap|Threads'`
   - Memory map summary: `cat /proc/<PID>/smaps_rollup`
   - Open FDs: `ls /proc/<PID>/fd | wc -l`
   - Network connections: `ss -tnp | grep <PID>`
   - CPU temperature: `cat /sys/class/thermal/thermal_zone0/temp`
3. Collect system-level stats:
   - `free -h`
   - `top -bn1 | grep Cpu`
   - `du -sh /home/arduino/alexa-custom/`
4. Get current timestamp: `date --iso-8601=seconds`
5. Write a new snapshot file to `reports/snapshot_<timestamp>.md` using the same format as previous snapshots.
6. Read all existing snapshot files from `reports/` and produce a **comparison table** showing how each key metric has evolved over time:
   - Columns: snapshot date/time, uptime, CPU%, RSS, PSS, private dirty, threads, open FDs, CPU temp, system idle%
   - Highlight any metric that changed by more than 10% between consecutive snapshots.
7. Add a brief **trend analysis** paragraph noting:
   - Is RSS growing (potential memory leak)?
   - Is CPU usage increasing or stabilizing?
   - Is temperature trending up?
   - Any other notable changes.
8. Print the comparison table and trend analysis to the terminal, and append the comparison as a new file `reports/comparison_<timestamp>.md`.
```

---

## Tips

- Run this prompt periodically (e.g. daily, or after a deploy) to build a time-series picture of resource usage.
- For automated tracking, consider wiring this prompt to a cron schedule via `/schedule`.
- The snapshot format is Markdown so reports are human-readable and diff-friendly in git.
- To track a memory leak over time, focus on the **RSS** and **Private dirty** columns — virtual size (VSZ) is less meaningful for Python.
