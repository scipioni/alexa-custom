    // ── Trigger graph view ────────────────────────────────────────────────

    let _graphAnimId = null, _graphNodes = [], _graphFlashMap = {};
    let _graphViewInited = false;

    const _G_ACOLOR = {
      say: '#60a5fa', shell: '#facc15', livekit: '#4ade80', telegram: '#7dd3fc',
      mqtt: '#fb923c', ask: '#a78bfa', tone: '#94a3b8', log: '#94a3b8',
      llm: '#a78bfa', set_volume: '#94a3b8',
    };

    function _gActionColor(actions) {
      const t = ((actions||[])[0]||{}).type||'';
      for (const [k,c] of Object.entries(_G_ACOLOR)) if (t.startsWith(k)) return c;
      return '#64748b';
    }

    const _G_ICON = {
      say: 'chat', shell: 'terminal', livekit: 'call', telegram: 'send',
      mqtt: 'sensors', ask: 'help', tone: 'notifications', log: 'description',
      llm: 'smart_toy', set_volume: 'volume_up',
    };
    function _gActionIcon(actions) {
      const t = ((actions||[])[0]||{}).type||'';
      for (const [k,v] of Object.entries(_G_ICON)) if (t.startsWith(k)) return v;
      return '▸';
    }
    function _gActionIcons(actions) {
      const seen = new Set();
      return (actions||[]).map(a => {
        const t = (a.type||'');
        for (const [k,v] of Object.entries(_G_ICON)) {
          if (t.startsWith(k)) { if (seen.has(k)) return null; seen.add(k); return v; }
        }
        if (!seen.has('?')) { seen.add('?'); return '▸'; }
        return null;
      }).filter(Boolean);
    }



    function _stopGraph() {
      if (_graphAnimId) { cancelAnimationFrame(_graphAnimId); _graphAnimId = null; }
      const c = document.getElementById('ww-graph-canvas');
      if (c && c._roCleanup) { c._roCleanup(); c._roCleanup = null; }
    }

    function _buildGraphData(cfg, canvasW) {
      if (!cfg) return { nodes: [], edges: [], totalH: 200 };
      const nodes = [], edges = [];
      // Layout constants
      const PAD = 6, WW_W = 148, WW_PAD = 9, LINE_H = 17, GAP = 46;
      const TR_X = PAD + WW_W + GAP;

      // Flat single-model layout: one wake-words box + one triggers grid container.
      const wws      = cfg.wake_words || [];   // flat string[]
      const triggers = cfg.triggers   || [];   // flat trigger list with with_wake bool

      // Trigger pill height: max of left-section (phrase+aliases) and right-section (ask panel).
      function trigH(t) {
        const TR_H = 32;
        const aliasH = TR_H + (t.aliases||[]).length * 15;
        const ask = (t.actions||[]).find(a => a.type === 'ask');
        if (!ask) return aliasH;
        const askH = 12 + 13 + (ask.on_reply||[]).length * 13;
        return Math.max(aliasH, askH);
      }

      let curY = PAD;

      // ── Wake-words box ────────────────────────────────────────────────────
      if (wws.length > 0) {
        const bh = WW_PAD * 2 + wws.length * LINE_H;
        nodes.push({ id: 'ww-node', type: 'wake-list', label: wws[0],
                     words: wws, x: PAD, y: curY, w: WW_W, h: bh });
        curY += bh;
      }

      // ── Triggers grid container ───────────────────────────────────────────
      if (triggers.length > 0) {
        const CONT_PAD = 10, COLS = 3, GRID_GAP_X = 8, GRID_GAP_Y = 6, TITLE_H = 18;
        const contX = TR_X;
        const contW = Math.max(180, canvasW - TR_X - PAD);
        const cellW = Math.floor((contW - CONT_PAD * 2 - (COLS - 1) * GRID_GAP_X) / COLS);
        const cellH = triggers.reduce((m, t) => Math.max(m, trigH(t)), 32);
        const rows  = Math.ceil(triggers.length / COLS);
        const contH = TITLE_H + CONT_PAD + rows * cellH + (rows - 1) * GRID_GAP_Y + CONT_PAD;
        const contY = PAD;

        nodes.push({ id: 'triggers-container', type: 'globals-container',
                     x: contX, y: contY, w: contW, h: contH });

        if (wws.length > 0) {
          const wwNode = nodes[0];
          const wwMid  = wwNode.y + wwNode.h / 2;
          const contMid = contY + contH / 2;
          wwNode.y = contMid - wwNode.h / 2;
          edges.push({ from: 'ww-node', to: 'triggers-container', isGlobal: true,
                       parts: [0.12, 0.52, 0.84].map(t0 => ({ t: t0 })) });
        }

        triggers.forEach((t, i) => {
          const col = i % COLS, row = Math.floor(i / COLS);
          const cx  = contX + CONT_PAD + col * (cellW + GRID_GAP_X);
          const cy  = contY + TITLE_H + CONT_PAD + row * (cellH + GRID_GAP_Y) + cellH / 2;
          nodes.push({ id: `g${i}`, type: 'global', label: t.phrase,
                       commands: t.commands || [],
                       aliases: t.aliases || [],
                       direct_match: !t.with_wake,
                       sleeping_only: !!t.sleeping_only,
                       actions: t.actions, x: cx, y: cy, w: cellW, h: cellH });
        });

        curY = contY + contH + PAD;
      } else {
        curY += PAD;
      }

      return { nodes, edges, totalH: curY };
    }

    function _rrect(ctx, x, y, w, h, r) {
      if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); return; }
      ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y); ctx.arcTo(x+w,y,x+w,y+r,r);
      ctx.lineTo(x+w,y+h-r); ctx.arcTo(x+w,y+h,x+w-r,y+h,r);
      ctx.lineTo(x+r,y+h); ctx.arcTo(x,y+h,x,y+h-r,r);
      ctx.lineTo(x,y+r); ctx.arcTo(x,y,x+r,y,r); ctx.closePath();
    }

    function _bezPt(ax, ay, bx, by, t) {
      const cx = (ax+bx)/2, u = 1-t;
      return { x: u*u*u*ax+3*u*u*t*cx+3*u*t*t*cx+t*t*t*bx,
               y: u*u*u*ay+3*u*u*t*ay+3*u*t*t*by+t*t*t*by };
    }

    function renderGraph(cfg) {
      if (!cfg) return;
      const canvas = document.getElementById('ww-graph-canvas');
      if (!canvas || !canvas.offsetParent) return;
      _stopGraph();

      const dpr = devicePixelRatio || 1;
      let built = _buildGraphData(cfg, canvas.offsetWidth);
      _graphNodes = built.nodes;
      let nodeById = Object.fromEntries(built.nodes.map(n => [n.id, n]));

      function resize() {
        const W = canvas.offsetWidth;
        built = _buildGraphData(cfg, W);
        _graphNodes = built.nodes;
        nodeById = Object.fromEntries(built.nodes.map(n => [n.id, n]));
        canvas.width = W * dpr;
        canvas.height = Math.max(built.totalH, 180) * dpr;
        canvas.style.height = Math.max(built.totalH, 180) + 'px';
      }
      resize();

      const ro = new ResizeObserver(resize);
      ro.observe(canvas);
      canvas._roCleanup = () => ro.disconnect();

      const ctx = canvas.getContext('2d');
      let hov = null, prevTs = performance.now(), _gLight = false;
      // Theme-aware text color helper — called per-draw, checked each frame.
      function _tc(alpha) {
        return _gLight ? `rgba(15,23,42,${alpha})` : `rgba(255,255,255,${alpha})`;
      }

      function drawGlobalsContainer(n) {
        const flash = _flashVal(n.id);
        const isHov = hov === n.id;
        const col   = '#60a5fa';
        ctx.save();
        ctx.shadowColor = col;
        ctx.shadowBlur  = flash > 0.05 ? flash * 24 : (isHov ? 8 : 0);
        ctx.beginPath(); _rrect(ctx, n.x, n.y, n.w, n.h, 7);
        ctx.fillStyle = 'rgba(96,165,250,0.04)'; ctx.fill();
        ctx.strokeStyle = isHov || flash > 0.3 ? col + 'aa' : col + '38';
        ctx.lineWidth = 1; ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.fillStyle = col + '80';
        ctx.font = 'bold 10px system-ui,sans-serif';
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText('GLOBAL TRIGGERS', n.x + 10, n.y + 9);
        ctx.restore();
      }

      function drawWwContainer(n) {
        const flash = _flashVal(n.id);
        const isHov = hov === n.id;
        const col   = '#fb923c';
        ctx.save();
        ctx.shadowColor = col;
        ctx.shadowBlur  = flash > 0.05 ? flash * 24 : (isHov ? 8 : 0);
        ctx.beginPath(); _rrect(ctx, n.x, n.y, n.w, n.h, 7);
        ctx.fillStyle = 'rgba(251,146,60,0.04)'; ctx.fill();
        ctx.strokeStyle = isHov || flash > 0.3 ? col + 'aa' : col + '38';
        ctx.lineWidth = 1; ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.fillStyle = col + '80';
        ctx.font = 'bold 10px system-ui,sans-serif';
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText('TRIGGERS', n.x + 10, n.y + 9);
        ctx.restore();
      }

      function drawWake(n) {
        const flash = _flashVal(n.id);
        const isHov  = hov === n.id;
        const col    = n.usesGlobals ? '#60a5fa' : '#fb923c';
        ctx.save();
        ctx.shadowColor = col;
        ctx.shadowBlur  = flash > 0.05 ? flash * 32 : (isHov ? 14 : 5);
        ctx.beginPath(); _rrect(ctx, n.x, n.y, n.w, n.h, 5);
        ctx.fillStyle = col + (flash > 0.1 ? Math.round(flash * 52).toString(16).padStart(2,'0') : '0e');
        ctx.fill();
        ctx.strokeStyle = flash > 0.1 ? col : (isHov ? col : col + 'bb');
        ctx.lineWidth   = flash > 0.1 ? 2 + flash : (isHov ? 2 : 1.5);
        ctx.stroke();
        ctx.shadowBlur  = 0;
        if (flash > 0.05) {
          const pulse = Math.sin(performance.now() / 150) * 0.5 + 0.5;
          const offset = 1.5 + pulse * 3.5;
          const alpha = 0.2 + (1 - pulse) * 0.5;
          ctx.beginPath();
          _rrect(ctx, n.x - offset, n.y - offset, n.w + offset * 2, n.h + offset * 2, 5 + offset);
          ctx.fillStyle = col + Math.round(alpha * 0.15 * 255).toString(16).padStart(2, '0');
          ctx.fill();
          ctx.strokeStyle = col + Math.round(alpha * 255).toString(16).padStart(2, '0');
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
        // Wake word list — each phrase rendered as a badge chip
        const WW_PAD = 9, LINE_H = 17;
        const allWords = n.words || [n.label];
        const AB_PAD_X = 6, AB_H = 15, AB_R = 3;
        ctx.font = '11px system-ui,sans-serif';
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        allWords.forEach((w, i) => {
          const abW = Math.min(ctx.measureText(w).width + AB_PAD_X * 2, n.w - WW_PAD * 2);
          const abX = n.x + WW_PAD;
          const abY = n.y + WW_PAD + LINE_H * i + (LINE_H - AB_H) / 2;
          ctx.beginPath(); _rrect(ctx, abX, abY, abW, AB_H, AB_R);
          ctx.fillStyle = i === 0 ? col + '28' : col + '18';
          ctx.fill();
          ctx.strokeStyle = i === 0 ? col + '99' : col + '66';
          ctx.lineWidth = 0.5;
          ctx.setLineDash([]);
          ctx.stroke();
          ctx.fillStyle = i === 0 ? col : col + 'bb';
          const maxCh = Math.floor((n.w - WW_PAD * 2 - AB_PAD_X * 2) / 6.2);
          const disp = w.length > maxCh ? w.slice(0, maxCh - 1) + '…' : w;
          ctx.fillText(disp, abX + AB_PAD_X, abY + AB_H / 2);
        });
        ctx.restore();
      }

      function drawTrig(n) {
        const flash = _flashVal(n.id);
        const isHov = hov === n.id;
        const isSleepingOnly = !!n.sleeping_only;
        const isDisabled = isSleepingOnly && _sttState !== 'sleeping';
        const col   = isDisabled ? '#6b7280' : (n.direct_match ? '#f97316' : _gActionColor(n.actions));
        const x = n.x, y = n.y - n.h / 2, w = n.w, h = n.h;
        ctx.save();
        if (isDisabled) ctx.globalAlpha = 0.45;
        ctx.shadowColor = col;
        ctx.shadowBlur  = flash > 0.05 ? flash * 28 : (isHov ? 10 : 0);
        ctx.beginPath(); _rrect(ctx, x, y, w, h, 5);
        ctx.fillStyle = flash > 0.05
          ? col + Math.round(flash * 44).toString(16).padStart(2,'0')
          : _tc(0.05);
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.fillStyle  = col;
        ctx.fillRect(x, y, 3 + flash * 2, h);   // accent bar widens on flash
        ctx.beginPath(); _rrect(ctx, x, y, w, h, 5);
        ctx.strokeStyle = flash > 0.05 ? col + 'ee' : (isHov ? col + 'cc' : col + '55');
        ctx.lineWidth   = flash > 0.05 ? 1.5 + flash : 1;
        ctx.lineWidth   = 1; ctx.stroke();
        if (flash > 0.05) {
          const pulse = Math.sin(performance.now() / 150) * 0.5 + 0.5;
          const offset = 1.5 + pulse * 3.5;
          const alpha = 0.2 + (1 - pulse) * 0.5;
          ctx.beginPath();
          _rrect(ctx, x - offset, y - offset, w + offset * 2, h + offset * 2, 5 + offset);
          ctx.fillStyle = col + Math.round(alpha * 0.15 * 255).toString(16).padStart(2, '0');
          ctx.fill();
          ctx.strokeStyle = col + Math.round(alpha * 255).toString(16).padStart(2, '0');
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
        const aliases   = n.aliases || [];
        const askAction = (n.actions||[]).find(a => a.type === 'ask');
        const replies   = askAction?.on_reply || [];
        const LINE_M = 16, LINE_A = 14;
        const LINE_Q = 13, LINE_R = 13;
        // Left section width; ask panel only shown when pill is wide enough.
        const LEFT_W = 155;
        const hasAsk = !!(askAction && w > LEFT_W + 50);
        const leftW  = hasAsk ? LEFT_W : w;
        // Phrase + aliases centred in full pill height (left section).
        const topH = LINE_M + aliases.length * LINE_A;
        const lblY = n.y - topH / 2 + LINE_M / 2;
        const icons     = _gActionIcons(n.actions);
        const ICON_STEP = 15;
        const ICONS_W   = icons.length > 0 ? icons.length * ICON_STEP + 4 : 0;
        const maxCh     = Math.floor((leftW - 16 - ICONS_W) / 6.2);
        ctx.textBaseline = 'middle';
        // Primary phrase
        ctx.font = '12px system-ui,sans-serif';
        ctx.textAlign = 'left';
        const phraseStr = n.label.length > maxCh ? n.label.slice(0, maxCh-1)+'…' : n.label;
        if (n.direct_match) {
          // Render phrase as a badge chip
          const PH_PAD_X = 7, PH_PAD_Y = 3, PH_R = 4;
          const phW = ctx.measureText(phraseStr).width + PH_PAD_X * 2;
          const phH = 16;
          const phX = x + 8, phY = lblY - phH / 2;
          ctx.beginPath(); _rrect(ctx, phX, phY, phW, phH, PH_R);
          ctx.fillStyle = col + '28';
          ctx.fill();
          ctx.strokeStyle = col + '99';
          ctx.lineWidth = 0.5;
          ctx.setLineDash([]);
          ctx.stroke();
          ctx.fillStyle = isHov || flash > 0.3 ? _tc(0.95) : col;
          ctx.fillText(phraseStr, phX + PH_PAD_X, lblY);
        } else {
          ctx.fillStyle = isHov || flash > 0.3 ? _tc(0.95) : _tc(0.80);
          ctx.fillText(phraseStr, x + 10, lblY);
        }
        // Action icons — right-aligned inside the left section
        ctx.font = '13px "Material Symbols Outlined"';
        ctx.textAlign = 'left';
        ctx.fillStyle = _tc(0.70);
        const iconsStartX = x + leftW - 4 - icons.length * ICON_STEP;
        icons.forEach((ic, i) => ctx.fillText(ic, iconsStartX + i * ICON_STEP, lblY));
        // Sleeping-only badge — moon icon in top-right corner of pill
        if (isSleepingOnly) {
          ctx.font = '11px "Material Symbols Outlined"';
          ctx.textAlign = 'right'; ctx.textBaseline = 'top';
          ctx.fillStyle = isDisabled ? '#6b7280' : '#a78bfa';
          ctx.fillText('bedtime', x + w - 5, y + 4);
          ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
          // "sleeping only" label below phrase when disabled
          if (isDisabled && aliases.length === 0) {
            ctx.font = '10px system-ui,sans-serif';
            ctx.fillStyle = '#6b7280';
            ctx.textAlign = 'left';
            ctx.fillText('solo da dormiente', x + 10, lblY + LINE_M / 2 + 7);
          }
        }
        // Aliases
        if (aliases.length) {
          ctx.fillStyle = isHov ? _tc(0.60) : _tc(0.45);
          ctx.font = '12px system-ui,sans-serif';
          ctx.textAlign = 'left';
          aliases.forEach((a, i) => {
            const ay = lblY + LINE_M / 2 + LINE_A / 2 + i * LINE_A;
            ctx.fillText(a.length > maxCh ? a.slice(0, maxCh-1)+'…' : a, x + 10, ay);
          });
        }
        // Ask panel — right section of the pill
        if (hasAsk) {
          const AX = x + LEFT_W;
          const AW = w - LEFT_W;
          // Tinted background (right portion only, clipped by outer pill shape)
          ctx.fillStyle = col + '0c';
          ctx.fillRect(AX, y + 1, AW - 1, h - 2);
          // Vertical separator
          ctx.strokeStyle = col + '55';
          ctx.lineWidth = 0.5;
          ctx.setLineDash([]);
          ctx.beginPath(); ctx.moveTo(AX, y + 5); ctx.lineTo(AX, y + h - 5); ctx.stroke();
          // Ask content centred in the pill height
          const askContentH = LINE_Q + replies.length * LINE_R;
          const askY0 = n.y - askContentH / 2;
          // Question text
          ctx.font = 'italic 11px system-ui,sans-serif';
          ctx.fillStyle = _tc(0.55);
          ctx.textAlign = 'left';
          const qText  = askAction.params?.text || '';
          const qMaxCh = Math.floor((AW - 14) / 5.5);
          ctx.fillText(qText.length > qMaxCh ? qText.slice(0, qMaxCh-1)+'…' : qText, AX + 8, askY0 + LINE_Q / 2);
          // Reply branches
          replies.forEach((r, i) => {
            const rY    = askY0 + LINE_Q + LINE_R * (i + 0.5);
            const isLast = i === replies.length - 1;
            const rIcons = _gActionIcons(r.actions || []);
            const rIconsW = rIcons.length * 13;
            const rMaxCh  = Math.floor((AW - 26 - rIconsW) / 5.8);
            ctx.font = '11px system-ui,sans-serif';
            ctx.fillStyle = col + '99';
            ctx.textAlign = 'left';
            ctx.fillText(isLast ? '└' : '├', AX + 8, rY);
            ctx.fillStyle = _tc(0.75);
            const rLabel = r.phrase || '';
            ctx.fillText(rLabel.length > rMaxCh ? rLabel.slice(0, rMaxCh-1)+'…' : rLabel, AX + 18, rY);
            ctx.font = '11px "Material Symbols Outlined"';
            ctx.textAlign = 'left';
            const riX = x + w - 5 - rIcons.length * 13;
            rIcons.forEach((ic, j) => ctx.fillText(ic, riX + j * 13, rY));
          });
        }
        ctx.restore();
      }

      function drawEdge(e, dt) {
        const a = nodeById[e.from], b = nodeById[e.to];
        if (!a || !b) return;
        const ax = a.x + a.w, ay = a.y + a.h / 2;
        // Container: enter its left-centre; pill: enter its left-centre (y is already centre)
        const bx = b.x;
        const by = (b.type === 'globals-container' || b.type === 'ww-container') ? b.y + b.h / 2 : b.y;
        const cx = (ax + bx) / 2;
        const col = e.isGlobal ? '#60a5fa' : _gActionColor(b.actions);
        ctx.beginPath();
        ctx.moveTo(ax, ay); ctx.bezierCurveTo(cx, ay, cx, by, bx, by);
        ctx.strokeStyle = col + (e.isGlobal ? '55' : '55');
        ctx.lineWidth   = 1.5; ctx.stroke();
        if (e.parts) {
          e.parts.forEach(p => {
            p.t = (p.t + dt * 0.28) % 1;
            const pt    = _bezPt(ax, ay, bx, by, p.t);
            const alpha = Math.round(180 * Math.sin(p.t * Math.PI)).toString(16).padStart(2,'0');
            ctx.beginPath(); ctx.arc(pt.x, pt.y, 2, 0, Math.PI * 2);
            ctx.fillStyle = col + alpha;
            ctx.shadowColor = col; ctx.shadowBlur = 7;
            ctx.fill(); ctx.shadowBlur = 0;
          });
        }
      }

      function frame(ts) {
        const dt = Math.min((ts - prevTs) / 1000, 0.05); prevTs = ts;
        _gLight = document.documentElement.getAttribute('data-theme') === 'light';
        const W = canvas.width / dpr, H = canvas.height / dpr;
        ctx.save(); ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, W, H);

        // Draw order: container bg → edges → trigger pills → wake box (on top)
        built.nodes.filter(n => n.type === 'globals-container').forEach(n => drawGlobalsContainer(n));
        built.edges.forEach(e => drawEdge(e, dt));
        built.nodes.filter(n => n.type === 'trig' || n.type === 'global').forEach(n => drawTrig(n));
        built.nodes.filter(n => n.type === 'wake' || n.type === 'wake-list').forEach(n => drawWake(n));

        ctx.restore();
        _graphAnimId = requestAnimationFrame(frame);
      }

      canvas.onmousemove = e => {
        const r = canvas.getBoundingClientRect(), mx = e.clientX-r.left, my = e.clientY-r.top;
        hov = null;
        let contHov = null;
        for (const n of built.nodes) {
          if (n.type === 'wake' || n.type === 'wake-list') {
            if (mx >= n.x && mx <= n.x+n.w && my >= n.y && my <= n.y+n.h) { hov = n.id; break; }
          } else if (n.type === 'globals-container') {
            // Container hover is a fallback — individual pills inside take priority
            if (mx >= n.x && mx <= n.x+n.w && my >= n.y && my <= n.y+n.h) contHov = n.id;
          } else if (mx >= n.x && mx <= n.x+n.w && my >= n.y-n.h/2 && my <= n.y+n.h/2) {
            hov = n.id; break;
          }
        }
        if (!hov) hov = contHov;
        canvas.style.cursor = hov ? 'pointer' : 'default';
      };
      canvas.onmouseleave = () => { hov = null; canvas.style.cursor = 'default'; };
      _graphAnimId = requestAnimationFrame(frame);
    }

    function _flashVal(id) {
      const e = _graphFlashMap[id];
      if (!e) return 0;
      const now = performance.now();
      const rem  = e.end - now;
      if (rem <= 0) { delete _graphFlashMap[id]; return 0; }
      const elapsed = (now - e.start) / 1000;
      return 0.65 + 0.35 * Math.sin(elapsed * Math.PI * 2 * 0.5); // 0.5 Hz, range [0.30, 1.0]
    }

    function _graphFlash(id, durationMs) {
      const now = performance.now();
      _graphFlashMap[id] = { start: now, end: now + (durationMs || 2500) };
    }

    function _graphFlashByPhrase(phrase) {
      const norm = phrase.toLowerCase().trim();
      for (const n of _graphNodes) {
        const labels = [n.label, ...(n.commands || [])];
        if (labels.some(l => l && l.toLowerCase().trim() === norm)) {
          _graphFlash(n.id, 2500);
          if (n.type === 'global') _graphFlash('triggers-container', 2500);
        }
      }
    }

    function _graphFlashByWord(word) {
      const ms   = ((_cfg?.recognition?.wake_window || 8) * 1000);
      const norm = word.toLowerCase().trim();
      for (const n of _graphNodes)
        if (n.type === 'wake-list') _graphFlash(n.id, ms);
    }

    // ── end graph view ────────────────────────────────────────────────────
