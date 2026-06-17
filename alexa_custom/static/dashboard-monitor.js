    // ── Telemetry & Diagnostics ───────────────────────────────────────────

    const _micRmsBuf = [];
    const _RMS_WIN = 40;

    function setVU(ch, lvl) {
      const count = Math.round(Math.sqrt(Math.max(0, Math.min(1, lvl))) * 20);
      const dv    = lvl > 1e-9 ? (20 * Math.log10(Math.max(lvl, 1e-9))).toFixed(1) : null;
      const segs  = document.getElementById(ch + '-segs-v').children;
      for (let i = 0; i < segs.length; i++) {
        const el = segs[i];
        if (el.classList.contains('rms-line')) continue;
        el.classList.toggle('on', i < count);
      }
      document.getElementById(ch + '-db').textContent = dv ? dv + ' dB' : '-∞ dB';

      if (ch === 'mic') {
        _micRmsBuf.push(lvl);
        if (_micRmsBuf.length > _RMS_WIN) _micRmsBuf.shift();
        const rms = _micRmsBuf.reduce((s, v) => s + v, 0) / _micRmsBuf.length;
        const rmsCount = Math.sqrt(Math.max(0, Math.min(1, rms))) * 20;
        const rmsLine = document.getElementById('mic-rms-line');
        if (rmsLine) rmsLine.style.bottom = (rmsCount / 20 * 100).toFixed(1) + '%';
      }
    }

    // ── sparkline ────────────────────────────────────────────────────────────
    let _sparkData = [];
    let _cpuLimit = 4;

    function _cpuColor(v, maxY) {
      const r = v / maxY;
      if (r >= 0.9) return '#f87171';
      if (r >= 0.6) return '#facc15';
      return '#4ade80';
    }

    function updateSparkline(m) {
      const load1  = m.load1  || 0;
      const load5  = m.load5  || 0;
      const load15 = m.load15 || 0;
      _sparkData.push(load1);
      if (_sparkData.length > 60) _sparkData.shift();

      const ramFreePct = m.ram_free_pct != null ? m.ram_free_pct : null;
      if (ramFreePct != null) {
        const ramUsed = 100 - ramFreePct;
        const ramColor = ramUsed > 90 ? '#f87171' : ramUsed > 75 ? '#facc15' : '#4ade80';
        const elRam = document.getElementById('ram-free-pct');
        const barRam = document.getElementById('ram-free-bar');
        if (elRam) { elRam.textContent = ramUsed.toFixed(0) + '%'; elRam.style.color = ramColor; }
        if (barRam) { barRam.style.width = ramUsed.toFixed(1) + '%'; barRam.style.backgroundColor = ramColor; }
      }

      const svg = document.getElementById('sparkline');
      if (!svg) return;

      const w = 200, h = 76;
      const cpuCount = m.cpu_count || 1;
      const maxY = _cpuLimit;
      const color = _cpuColor(load1, maxY);
      const n = _sparkData.length;

      const pad = { t: 6, b: 6, l: 2, r: 2 };
      const cw = w - pad.l - pad.r;
      const ch = h - pad.t - pad.b;

      const toX = i => pad.l + (i / (n - 1 || 1)) * cw;
      const toY = v => pad.t + ch - Math.min(ch, Math.max(0, (v / maxY) * ch));

      const pts = _sparkData.map((v, i) => ({ x: toX(i), y: toY(v), c: _cpuColor(v, maxY) }));

      // smooth cubic bezier path
      function smooth(points) {
        if (points.length < 2) return '';
        let d = 'M' + points[0].x.toFixed(1) + ',' + points[0].y.toFixed(1);
        for (let i = 1; i < points.length; i++) {
          const p0 = points[i - 1], p1 = points[i];
          const cx = (p0.x + p1.x) / 2;
          d += ' C' + cx.toFixed(1) + ',' + p0.y.toFixed(1) + ' ' + cx.toFixed(1) + ',' + p1.y.toFixed(1) + ' ' + p1.x.toFixed(1) + ',' + p1.y.toFixed(1);
        }
        return d;
      }

      const linePath = smooth(pts);
      const last = pts[pts.length - 1] || { x: pad.l, y: pad.t + ch };
      const fillPath = linePath + ' L' + last.x.toFixed(1) + ',' + (pad.t + ch) + ' L' + pad.l + ',' + (pad.t + ch) + 'Z';

      // grid lines at 25 / 50 / 75 % of maxY
      const gridLines = [0.25, 0.5, 0.75].map(f => {
        const gy = toY(f * maxY);
        return '<line x1="' + pad.l + '" y1="' + gy.toFixed(1) + '" x2="' + (w - pad.r) + '" y2="' + gy.toFixed(1) + '" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>';
      }).join('');

      // 1-core load threshold dashed line
      const threshY = toY(2);
      const threshLine = threshY >= pad.t && threshY <= pad.t + ch
        ? '<line x1="' + pad.l + '" y1="' + threshY.toFixed(1) + '" x2="' + (w * 0.55).toFixed(1) + '" y2="' + threshY.toFixed(1) + '" stroke="var(--info)" stroke-width="0.8" stroke-dasharray="4,4" opacity="0.55"/>'
        : '';

      svg.innerHTML =
        '<defs>'
        + '<linearGradient id="cg" x1="0" y1="0" x2="1" y2="0">'
        + pts.map((p, i) => '<stop offset="' + (i / (n - 1 || 1) * 100).toFixed(0) + '%" stop-color="' + p.c + '"/>').join('')
        + '</linearGradient>'
        + '<linearGradient id="fg" x1="0" y1="0" x2="0" y2="1">'
        + '<stop offset="0%" stop-color="' + color + '" stop-opacity="0.35"/>'
        + '<stop offset="100%" stop-color="' + color + '" stop-opacity="0.0"/>'
        + '</linearGradient>'
        + '<filter id="glow" x="-20%" y="-60%" width="140%" height="220%">'
        + '<feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="blur"/>'
        + '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>'
        + '</filter>'
        + '</defs>'
        + gridLines
        + threshLine
        + '<path d="' + fillPath + '" fill="url(#fg)"/>'
        + '<path d="' + linePath + '" fill="none" stroke="url(#cg)" stroke-width="1.8" stroke-linecap="round" filter="url(#glow)"/>'
        + '<circle cx="' + last.x.toFixed(1) + '" cy="' + last.y.toFixed(1) + '" r="3" fill="' + color + '" opacity="0.9" filter="url(#glow)">'
        + '<animate attributeName="opacity" values="0.9;0.25;0.9" dur="1.8s" repeatCount="indefinite"/>'
        + '</circle>';

      const cpuLoad = document.getElementById('cpu-load');
      if (cpuLoad) { cpuLoad.textContent = load1.toFixed(2); cpuLoad.style.color = color; }

      const badge = document.getElementById('cpu-cores-badge');
      if (badge) badge.textContent = cpuCount + ' core' + (cpuCount !== 1 ? 's' : '');

      const el5   = document.getElementById('cpu-load5');
      const el15  = document.getElementById('cpu-load15');
      const bar5  = document.getElementById('cpu-bar5');
      const bar15 = document.getElementById('cpu-bar15');
      if (el5)  { el5.textContent  = load5.toFixed(2);  el5.style.color  = _cpuColor(load5,  maxY); }
      if (el15) { el15.textContent = load15.toFixed(2); el15.style.color = _cpuColor(load15, maxY); }
      if (bar5)  { bar5.style.width  = Math.min(100, load5  / maxY * 100).toFixed(1) + '%'; bar5.style.backgroundColor  = _cpuColor(load5,  maxY); }
      if (bar15) { bar15.style.width = Math.min(100, load15 / maxY * 100).toFixed(1) + '%'; bar15.style.backgroundColor = _cpuColor(load15, maxY); }
    }
