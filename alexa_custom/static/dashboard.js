// build vertical segmented VU meters
    ['mic-segs-v', 'spk-segs-v'].forEach(id => {
      const c = document.getElementById(id);
      for (let i = 0; i < 20; i++) {
        const s = document.createElement('span');
        s.className = 'seg-v';
        c.appendChild(s);
      }
    });

    let ws = null, reconnTimer = null, _restarting = false, _reconnDelay = 1000;
    let _lastWakeWord = '', _cfg = null, _sttState = 'listening';
    const parts = {};
    const _heroTimers = {};

    // ── volume control ─────────────────────────────────────────────────────
    function _setSliderFill(vol) {
      const slider = document.getElementById('volume-slider');
      if (!slider) return;
      const pct = Math.round(vol * 100);
      slider.style.setProperty('--vol-pct', pct + '%');
      const color = getComputedStyle(document.documentElement).getPropertyValue('--info').trim() || '#60a5fa';
      slider.style.setProperty('--vol-color', color);
    }

    function initVolumeSlider(volume) {
      const slider = document.getElementById('volume-slider');
      const percent = document.getElementById('volume-percent');
      if (slider && percent) {
        slider.value = volume * 100;
        percent.textContent = Math.round(volume * 100) + '%';
        _setSliderFill(volume);
        slider.oninput = () => {
          percent.textContent = slider.value + '%';
          _setSliderFill(parseFloat(slider.value) / 100);
        };
        slider.onmousedown = () => { slider.classList.add('dragging'); };
        slider.onmouseup = () => {
          slider.classList.remove('dragging');
          sendVolumeControl('set_volume', {volume: parseFloat(slider.value) / 100});
          playBeepForVolume(parseFloat(slider.value) / 100);
        };
      }
    }

    function playBeepForVolume(volume) {
      if (volume <= 0.01) return;
      if (volume < 0.3) {
        sendVolumeControl('beep', {frequency: 330, duration: 100});
      } else if (volume < 0.7) {
        sendVolumeControl('beep', {frequency: 440, duration: 100});
      } else {
        sendVolumeControl('beep', {frequency: 523, duration: 100});
      }
    }

    function sendVolumeControl(type, payload) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({type: 'control', action: type, ...payload}));
    }
    function connect() {
      clearTimeout(reconnTimer);
      if (ws) { ws.onclose = ws.onerror = null; try { ws.close(); } catch(e) {} }
      ws = new WebSocket('ws://' + location.host + '/ws');
      ws.onopen = () => {
        _reconnDelay = 1000;
        wsInd(true);
        if (_restarting) {
          setSt('Restarting UI…', null);
          setTimeout(() => location.reload(), 200);
        }
      };
      ws.onclose = () => {
        wsInd(false); ws = null;
        if (_restarting) setSt('Waiting for server…', null);
        reconnTimer = setTimeout(connect, _reconnDelay);
        _reconnDelay = Math.min(_reconnDelay * 2, 8000);
      };
      ws.onerror = () => {
        clearTimeout(reconnTimer);
        reconnTimer = setTimeout(connect, _reconnDelay);
        _reconnDelay = Math.min(_reconnDelay * 2, 8000);
      };
      ws.onmessage = (e) => { try { handle(JSON.parse(e.data)); } catch(_) {} };
    }

    function wsInd(up) {
      const el = document.getElementById('ws-ind');
      el.textContent = up ? 'WS connected' : 'WS reconnecting…';
      el.className   = up ? 'ok' : '';
      const dot = document.getElementById('cdot');
      dot.className = up ? 'sdot ok' : 'sdot warn';
    }

    function handle(m) {
      switch (m.type) {
        case 'hello': {
          _restarting = false;
          const rb = document.getElementById('btn-restart');
          rb.disabled = false; rb.classList.remove('spinning');
          setSt(m.status, m.room);
          (m.participants || []).forEach(p => parts[p.identity] = p.tracks);
          renderParts();
          setAudio(m.audio_connected, m.audio_conn_type);
          setStt(m.stt_state, m.stt_text, m);
          setStatusListening(m.stt_state === 'wake' || m.stt_state === 'partial' || m.stt_state === 'transcribing');
          if (m.actions_config && Object.keys(m.actions_config).length) { _cfg = m.actions_config; renderActions(_cfg); }
          setRoomStatus(m.room_status || 'closed', m.room_answer_timeout || 0);
          _checkRoomConfig(m);
          if (m.history) {
            const hlEl = document.getElementById('hl');
            if (hlEl) {
              hlEl.innerHTML = '';
              m.history.forEach(session => {
                addSessionHistory(session);
              });
            }
          }
          if (m.input_gain != null) {
            const el = document.getElementById('mic-gain');
            if (el) el.textContent = '×' + m.input_gain.toFixed(1);
          }
          if (m.cpu_limit != null) _cpuLimit = m.cpu_limit;
          if (m.output_volume != null) {
            initVolumeSlider(m.output_volume);
          }
          break;
        }
        case 'starting':           setSt('Starting…', null); break;
        case 'idle':               setSt('Ready', null); break;
        case 'connecting':         setSt('Connecting…', null); break;
        case 'connected':          setSt('Connected', m.room); setRoomStatus('in_call', 0); break;
        case 'disconnected':       setSt('Disconnected — reconnecting…', null); setRoomStatus('closed', 0); break;
        case 'reconnecting':       setSt('Reconnecting…', null); break;
        case 'empty_room_timeout': setSt('Disconnected — empty room', null); break;
        case 'participant_joined':
          parts[m.identity] = parts[m.identity] || 0; renderParts(); break;
        case 'participant_left':
          delete parts[m.identity]; renderParts(); break;
        case 'track_subscribed':
          parts[m.identity] = (parts[m.identity] || 0) + 1; renderParts(); break;
        case 'track_unsubscribed':
          if (m.identity in parts) parts[m.identity] = Math.max(0, (parts[m.identity]||1)-1);
          renderParts(); break;
        case 'volume_update': {
          setVU('mic', m.mic||0); setVU('spk', m.spk||0);
          
          if (m.adaptive) {
            const rmsLine = document.getElementById('mic-rms-line');
            if (rmsLine && m.rms_threshold !== undefined) {
              const rmsCount = Math.sqrt(Math.max(0, Math.min(1, m.rms_threshold))) * 20;
              rmsLine.style.bottom = (rmsCount / 20 * 100).toFixed(1) + '%';
              rmsLine.classList.add('adaptive');
              rmsLine.title = `Adaptive RMS: ${m.rms_threshold.toFixed(3)}`;
            }
            if (m.confidence !== undefined && m.confidence !== null) {
                // optionally show confidence
            }
          }
          
          const wave = document.querySelector('#hero .stt-wave');
          if (wave && m.mic > 0) {
            const hasActive = wave.classList.contains('wv-active');
            const hasListen = wave.classList.contains('wv-listen');
            if (hasActive) {
              const speed = Math.max(0.12, 0.25 - m.mic * 0.18);
              wave.style.setProperty('--sw-speed', speed.toFixed(2) + 's');
            } else if (hasListen) {
              const speed = Math.max(0.3, 0.55 - m.mic * 0.3);
              wave.style.setProperty('--sw-speed', speed.toFixed(2) + 's');
            }
          }
          const hero = document.getElementById('hero');
          if (hero && hero.classList.contains('wave-glow')) {
            hero.style.setProperty('--glow-power', Math.min(1, (m.mic || 0) * 3).toFixed(2));
          }
          break;
        }
        case 'audio_status':  setAudio(m.connected, m.conn_type); break;
        case 'stt': {
          const s = m.state;
          setStatusListening(s === 'wake' || s === 'partial' || s === 'transcribing');
          if (s === 'wake' && m.word && m.word !== '(reply)') {
            _lastWakeWord = m.word;
            updateInteraction(m.word, '');
            _graphFlashByWord(m.word);
          }
          if (s === 'partial') {
            updateInteraction(_lastWakeWord, m.text);
            if (!_lastWakeWord) dimNonMatchingReplies(m.text || '');
          }
          if (s === 'matched') {
            const isReply = !_lastWakeWord;
            updateInteraction(_lastWakeWord, (m.transcript||'') + ' → ' + (m.trigger||''), true);
            highlightTrigger(m.trigger||'', isReply);
            _graphFlashByPhrase(m.trigger||'');
            clearReplyDim();
            _lastWakeWord = '';
          }
          if (s === 'nomatch') {
            clearReplyDim();
            const txt = m.transcript || m.text || '';
            if (_lastWakeWord) {
              updateInteraction(_lastWakeWord, (txt ? '"'+txt+'" ' : '') + '✗ no match', true);
            }
            _lastWakeWord = '';
          }
          if (s === 'skipped') {
            clearReplyDim();
            updateInteraction(m.word||'', (m.text ? '"'+m.text+'" ' : '') + '⊘ ignored', true);
            _lastWakeWord = '';
          }
          if (s === 'llm_thinking') {
            setLlmBadgeThinking(true);
            setLlmStatusDot(true);
          }
          if (s === 'llm_reply') {
            setLlmBadgeThinking(false);
            setLlmStatusDot(false);
          }
          if (s === 'llm_unreachable') {
            setLlmBadgeThinking(false);
            setLlmStatusDot(false);
          }
          setStt(s, m.text||m.word||m.transcript||m.reply||'', m);
          break;
        }
        case 'log':       addLog(m); break;
        case 'restarting': {
          _restarting = true;
          const b = document.getElementById('btn-restart');
          b.disabled = true; b.classList.add('spinning');
          setSt('Restarting…', null);
          break;
        }
        case 'room_status': setRoomStatus(m.status, m.timeout||0); break;
        case 'system_stats': {
          updateSparkline(m);
          if (m.output_volume != null) {
            const slider = document.getElementById('volume-slider');
            const percent = document.getElementById('volume-percent');
            if (slider && percent) {
              const current = parseFloat(slider.value) / 100;
              if (Math.abs(m.output_volume - current) > 0.005) {
                slider.value = m.output_volume * 100;
                percent.textContent = Math.round(m.output_volume * 100) + '%';
                _setSliderFill(m.output_volume);
              }
            }
          }
          if (m.input_gain != null) {
            const el = document.getElementById('mic-gain');
            if (el) el.textContent = '×' + m.input_gain.toFixed(1);
          }
          break;
        }
        case 'history_item': addSessionHistory(m.session); break;
        case 'history_cleared': {
          document.getElementById('hl').innerHTML = '';
          updateHistoryVisibility();
          break;
        }
        case 'history_flagged': {
          const cards = document.querySelectorAll('.he[data-id="' + esc(m.session_id) + '"]');
          cards.forEach(card => {
            card.classList.add('fp-flagged');
            const row = card.querySelector('.he-action-row');
            if (row) {
              row.innerHTML = '<span class="hflagged" style="font-size:9px;color:var(--nomatch);font-weight:bold;margin-left:auto;">⚠️ Flagged</span>';
            }
          });
          break;
        }
        case 'error': setSt('Error: ' + (m.msg||'unknown'), null); break;
      }
    }

    const _RS = {
      closed:  { icon: 'phone_disabled', label: 'Closed',   sub: 'No active call',        cls: '' },
      waiting: { icon: 'phone_callback', label: 'Waiting…', sub: 'Polling for caller',     cls: 'rs-waiting' },
      in_call: { icon: 'phone_in_talk',  label: 'In Call',  sub: 'Call active',            cls: '' },
    };
    let _donutStart = 0, _donutTotal = 0, _donutTimer = null;
    const _donutCirc = 2 * Math.PI * 15;
    function _updateDonut() {
      if (!_donutTotal) return;
      const elapsed = (Date.now() - _donutStart) / 1000;
      const remaining = Math.max(0, _donutTotal - elapsed);
      const pct = remaining / _donutTotal;
      const fill = document.getElementById('donut-fill');
      const label = document.getElementById('donut-label');
      if (fill) fill.setAttribute('stroke-dashoffset', (_donutCirc * (1 - pct)).toFixed(1));
      if (label) label.textContent = Math.ceil(remaining) + 's';
      if (remaining <= 0) { clearInterval(_donutTimer); _donutTimer = null; }
    }
    function _showDonut(timeout) {
      _donutStart = Date.now();
      _donutTotal = timeout;
      const wrap = document.getElementById('donut-wrap');
      if (wrap) wrap.classList.add('visible');
      _updateDonut();
      if (_donutTimer) clearInterval(_donutTimer);
      _donutTimer = setInterval(_updateDonut, 200);
    }
    function _hideDonut() {
      if (_donutTimer) { clearInterval(_donutTimer); _donutTimer = null; }
      _donutTotal = 0;
      const wrap = document.getElementById('donut-wrap');
      if (wrap) wrap.classList.remove('visible');
    }
    function _checkRoomConfig(m) {
      if (m.livekit_configured && m.telegram_configured) return;
      const missing = [];
      if (!m.livekit_configured) missing.push('LiveKit');
      if (!m.telegram_configured) missing.push('Telegram');
      document.getElementById('rs-icon').textContent = 'warning';
      document.getElementById('rs-label').textContent = 'Calls disabled';
      document.getElementById('rs-sub').textContent = 'Missing: ' + missing.join(', ');
    }

    function setRoomStatus(status, timeout) {
      const cfg = _RS[status] || _RS.closed;
      const body = document.getElementById('room-status-body');
      body.className = status === 'in_call' ? 'rs-active' : '';
      document.getElementById('rs-icon').textContent  = cfg.icon;
      document.getElementById('rs-label').textContent = cfg.label;
      let sub = cfg.sub;
      if (status === 'waiting' && timeout > 0) sub += ' (' + timeout + 's)';
      document.getElementById('rs-sub').textContent = sub;
      const pList = document.getElementById('room-participants-list');
      if (status === 'in_call') {
        const names = Object.keys(parts);
        pList.textContent = names.length ? '● ' + names.join(', ') : '';
        pList.style.display = names.length ? 'block' : 'none';
      } else {
        pList.style.display = 'none';
      }
      if (status === 'waiting' && timeout > 0) {
        _showDonut(timeout);
      } else {
        _hideDonut();
      }
    }

    function setLlmBadgeThinking(on) {
      const el = document.getElementById('llm-model-name');
      if (el) el.classList.toggle('thinking', on);
    }

    function setLlmStatusDot(thinking) {
      const dot = document.getElementById('llm-status-dot');
      if (!dot) return;
      dot.classList.toggle('thinking', thinking);
    }

    function heroAnim(cls, duration) {
      const h = document.getElementById('hero');
      clearTimeout(_heroTimers[cls]);
      h.classList.remove(cls);
      void h.offsetWidth;
      h.classList.add(cls);
      _heroTimers[cls] = setTimeout(() => h.classList.remove(cls), duration);
    }

    const _trigTimers = {};
    function _trigPhrase(el) {
      const p = el.querySelector('.trig-phrase, .trig-reply-phrase, .trig-else-phrase');
      return p ? p.textContent.replace('⮑', '').replace(/\(.*?\)/g, '').trim().toLowerCase() : '';
    }

    function highlightTrigger(phrase, isReply) {
      if (!phrase) return;
      const norm = phrase.toLowerCase().trim();
      document.querySelectorAll('.atrig').forEach(el => {
        if (_trigPhrase(el) === norm) {
          const cls = isReply ? 'trig-reply-hit' : 'trig-hit';
          clearTimeout(_trigTimers[norm]);
          el.classList.remove('trig-hit', 'trig-reply-hit');
          void el.offsetWidth;
          el.classList.add(cls);
          _trigTimers[norm] = setTimeout(() => el.classList.remove(cls), 4000);
        }
      });
    }

    function dimNonMatchingReplies(partial) {
      const norm = partial.toLowerCase().trim();
      document.querySelectorAll('.atrig').forEach(el => {
        const isReply = !!el.querySelector('.trig-reply-phrase, .trig-else-phrase');
        if (!isReply) return;
        const p = _trigPhrase(el);
        if (norm && !p.includes(norm) && !norm.includes(p)) {
          el.classList.add('trig-dim');
        } else {
          el.classList.remove('trig-dim');
        }
      });
    }

    function clearReplyDim() {
      document.querySelectorAll('.atrig.trig-dim').forEach(el => el.classList.remove('trig-dim'));
    }

    function updateInteraction(word, text, finish) {
      if (!word) return;
      const norm = word.toLowerCase().trim();
      document.querySelectorAll('.ww-card').forEach(g => {
        const ww = g.getAttribute('data-word').toLowerCase();
        const aa = (g.getAttribute('data-aliases')||'').toLowerCase().split(',');
        if (ww === norm || aa.includes(norm)) {
          g.classList.add('ww-active');
          const i = g.querySelector('.ainteract');
          if (i) {
            i.textContent = text;
            if (finish) setTimeout(() => {
              if (_lastWakeWord === '') { g.classList.remove('ww-active'); i.textContent = ''; }
            }, 3000);
          }
        } else {
          g.classList.remove('ww-active');
          const i = g.querySelector('.ainteract');
          if (i) i.textContent = '';
        }
      });
    }

    function setSt(_text, room) {
      if (room !== null)
        document.getElementById('room').textContent = room || '';
    }

    function setStatusListening(listening) {
      const hero = document.getElementById('hero');
      if (listening) {
        hero.classList.add('wave-glow');
      } else {
        hero.classList.remove('wave-glow');
        hero.style.removeProperty('--glow-power');
      }
    }

    function renderParts() {
      const keys = Object.keys(parts);
      const pList = document.getElementById('room-participants-list');
      if (!pList) return;
      if (keys.length) {
        pList.textContent = '● ' + keys.join(', ');
        pList.style.display = 'block';
      } else {
        pList.textContent = '';
        pList.style.display = 'none';
      }
    }

    function _aliases(list) {
      return (list && list.length) ? ' <span class="aalias-inline">(' + esc(list.join(', ')) + ')</span>' : '';
    }

    function _actionBadge(label) {
      if (!label) return '';
      const l = label.toLowerCase();
      if (l.startsWith('say'))           return '<span class="abadge abadge-say">say</span>';
      if (l.startsWith('shell'))         return '<span class="abadge abadge-shell">shell</span>';
      if (l.startsWith('livekit'))       return '<span class="abadge abadge-livekit">livekit</span>';
      if (l.startsWith('telegram'))      return '<span class="abadge abadge-telegram">tg</span>';
      if (l.startsWith('mqtt'))          return '<span class="abadge abadge-mqtt">mqtt</span>';
      if (l.startsWith('ask'))           return '<span class="abadge abadge-ask">ask</span>';
      if (l.startsWith('tone'))          return '<span class="abadge abadge-tone">tone</span>';
      if (l.startsWith('log'))           return '<span class="abadge abadge-log">log</span>';
      if (l.startsWith('llm'))           return '<span class="abadge abadge-llm">llm</span>';
      if (l.startsWith('set_volume'))    return '<span class="abadge abadge-other">vol</span>';
      const short = label.length > 9 ? label.slice(0, 9) + '…' : label;
      return '<span class="abadge abadge-other">' + esc(short) + '</span>';
    }

    function _badges(actions) {
      return (actions || []).map(a => _actionBadge(a.type)).join('');
    }

    function renderTrigTree(actions) {
      let res = '';
      (actions || []).forEach(a => {
        if (a.type === 'ask' && (a.on_reply || a.on_else)) {
          res += '<div class="trig-replies">';
          (a.on_reply || []).forEach(r => {
            res += '<div class="atrig"><div class="trig-row">'
              + '<span class="trig-reply-phrase">⮑ ' + esc(r.phrase) + '</span>'
              + '<span class="trig-badges">' + _badges(r.actions) + '</span>'
              + '</div>' + renderTrigTree(r.actions) + '</div>';
          });
          if (a.on_else && a.on_else.length) {
            res += '<div class="atrig"><div class="trig-row">'
              + '<span class="trig-else-phrase">⮑ else</span>'
              + '<span class="trig-badges">' + _badges(a.on_else) + '</span>'
              + '</div></div>';
          }
          res += '</div>';
        }
      });
      return res;
    }

    function renderActions(cfg) {
      if (!cfg) return;
      renderGraph(cfg);
      if (!_graphViewInited) {
        _graphViewInited = true;
      }

      // LLM section — render in monitoring column
      if (cfg.llm) {
        const llm = cfg.llm;
        const aiSection = document.getElementById('ai-section');
        const aiContent = document.getElementById('ai-content');
        if (aiSection && aiContent) {
          aiSection.style.display = 'block';
          aiContent.innerHTML = '<div><span id="llm-status-dot"></span> <span class="llm-model-tag">' + esc(llm.model) + '</span></div>'
            + '<div class="llm-attr">@ ' + esc(llm.host) + '</div>'
            + (llm.fallback ? '<div class="llm-attr" style="color:var(--llm);opacity:0.7">⮑ on no match</div>' : '');
        }

        const modelEl = document.getElementById('llm-model-name');
        if (modelEl) modelEl.textContent = llm.model.split('/').pop();
      }
    }

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
      const TR_W = Math.max(130, canvasW - TR_X - PAD);
      const TR_H = 32, ITEM_GAP = 7, GROUP_GAP = 22;

      const wws    = cfg.wake_words      || [];
      const globals = cfg.global_triggers || [];

      function boxH(w) {
        return WW_PAD * 2 + (1 + (w.aliases||[]).length) * LINE_H;
      }
      // Trigger pill height: max of left-section (phrase+aliases) and right-section (ask panel).
      function trigH(t) {
        const aliasH = TR_H + (t.aliases||[]).length * 15;
        const ask = (t.actions||[]).find(a => a.type === 'ask');
        if (!ask) return aliasH;
        const askH = 12 + 13 + (ask.on_reply||[]).length * 13; // V_PAD + LINE_Q + n*LINE_R
        return Math.max(aliasH, askH);
      }

      const globalUserNodes = [];
      let curY = PAD;

      wws.forEach((w, wi) => {
        const trigs = w.triggers || [];
        const bh    = boxH(w);
        const wwNode = { id: `w${wi}`, type: 'wake', label: w.word,
                         aliases: w.aliases || [], wi,
                         x: PAD, y: curY, w: WW_W, h: bh,
                         usesGlobals: trigs.length === 0 && globals.length > 0,
                         skipUnmatched: !!w.skip_unmatched_inline };
        nodes.push(wwNode);

        if (trigs.length > 0) {
          const CONT_PAD = 10, COLS = 3, GRID_GAP_X = 8, GRID_GAP_Y = 6, TITLE_H = 18;
          const contX = TR_X;
          const contW = Math.max(180, canvasW - TR_X - PAD);
          const cellW = Math.floor((contW - CONT_PAD * 2 - (COLS - 1) * GRID_GAP_X) / COLS);
          const cellH = trigs.reduce((m, t) => Math.max(m, trigH(t)), TR_H);
          const rows  = Math.ceil(trigs.length / COLS);
          const contH = TITLE_H + CONT_PAD + rows * cellH + (rows - 1) * GRID_GAP_Y + CONT_PAD;
          const groupH = Math.max(bh, contH);
          wwNode.y = curY + Math.max(0, (contH - bh) / 2);
          const contY = curY;
          nodes.push({ id: `wc${wi}`, type: 'ww-container',
                       x: contX, y: contY, w: contW, h: contH, wi });
          edges.push({ from: `w${wi}`, to: `wc${wi}`,
                       parts: [0.12, 0.52, 0.84].map(t0 => ({ t: t0 })) });
          trigs.forEach((t, ti) => {
            const col = ti % COLS, row = Math.floor(ti / COLS);
            const cx  = contX + CONT_PAD + col * (cellW + GRID_GAP_X);
            const cy  = contY + TITLE_H + CONT_PAD + row * (cellH + GRID_GAP_Y) + cellH / 2;
            nodes.push({ id: `t${wi}_${ti}`, type: 'trig', label: t.phrase,
                         aliases: t.aliases || [], direct_match: !!t.direct_match,
                         sleeping_only: !!t.sleeping_only,
                         actions: t.actions, x: cx, y: cy, w: cellW, h: cellH,
                         containerId: `wc${wi}` });
          });
          curY += groupH + GROUP_GAP;
        } else {
          globalUserNodes.push(wwNode);
          curY += bh + ITEM_GAP;
        }
      });

      if (globals.length > 0) {
        if (globalUserNodes.length > 0) curY += GROUP_GAP;

        // Grid layout inside a single container rectangle.
        const CONT_PAD = 10, COLS = 3, GRID_GAP_X = 8, GRID_GAP_Y = 6, TITLE_H = 18;
        const contX  = TR_X;
        const contW  = Math.max(180, canvasW - TR_X - PAD);
        const cellW  = Math.floor((contW - CONT_PAD * 2 - (COLS - 1) * GRID_GAP_X) / COLS);
        const cellH  = globals.reduce((m, t) => Math.max(m, trigH(t)), TR_H);
        const rows   = Math.ceil(globals.length / COLS);
        const contH  = TITLE_H + CONT_PAD + rows * cellH + (rows - 1) * GRID_GAP_Y + CONT_PAD;
        const globsY0 = curY;

        nodes.push({ id: 'globals-container', type: 'globals-container',
                     x: contX, y: globsY0, w: contW, h: contH });

        globals.forEach((t, gi) => {
          const col = gi % COLS, row = Math.floor(gi / COLS);
          const cx  = contX + CONT_PAD + col * (cellW + GRID_GAP_X);
          const cy  = globsY0 + TITLE_H + CONT_PAD + row * (cellH + GRID_GAP_Y) + cellH / 2;
          nodes.push({ id: `g${gi}`, type: 'global', label: t.phrase,
                       aliases: t.aliases || [], direct_match: !!t.direct_match,
                       sleeping_only: !!t.sleeping_only,
                       actions: t.actions, x: cx, y: cy, w: cellW, h: cellH });
        });

        // Re-centre global-user wake boxes alongside the container; one edge each.
        if (globalUserNodes.length > 0) {
          const stackH = globalUserNodes.reduce((s, n) => s + n.h, 0)
                         + (globalUserNodes.length - 1) * ITEM_GAP;
          let wy = globsY0 + Math.max(0, (contH - stackH) / 2);
          globalUserNodes.forEach(n => { n.y = wy; wy += n.h + ITEM_GAP; });
          globalUserNodes.forEach(wn =>
            edges.push({ from: wn.id, to: 'globals-container', isGlobal: true,
                         parts: [0.12, 0.52, 0.84].map(t0 => ({ t: t0 })) })
          );
        }
        curY = globsY0 + contH + PAD;
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
        // Primary word — rendered as a badge chip
        const WW_PAD = 9, LINE_H = 17;
        ctx.font = 'bold 12px system-ui,sans-serif';
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        const wwStr = n.label.toUpperCase();
        const WB_PAD_X = 7, WB_H = 18, WB_R = 4;
        const wwW = ctx.measureText(wwStr).width + WB_PAD_X * 2;
        const wwBX = n.x + WW_PAD, wwBY = n.y + WW_PAD;
        ctx.beginPath(); _rrect(ctx, wwBX, wwBY, wwW, WB_H, WB_R);
        ctx.fillStyle = col + '28';
        ctx.fill();
        ctx.strokeStyle = col + '99';
        ctx.lineWidth = 0.5;
        ctx.setLineDash([]);
        ctx.stroke();
        ctx.fillStyle = col;
        ctx.fillText(wwStr, wwBX + WB_PAD_X, wwBY + WB_H / 2);
        // skip_unmatched_inline indicator — small ⊘ in top-right corner
        if (n.skipUnmatched) {
          ctx.font = '11px system-ui,sans-serif';
          ctx.textAlign = 'right'; ctx.textBaseline = 'top';
          ctx.fillStyle = col + '99';
          ctx.fillText('⊘', n.x + n.w - 5, n.y + 4);
          ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        }
        // Aliases — same badge chip style
        if (n.aliases.length) {
          ctx.font = '11px system-ui,sans-serif';
          const AB_PAD_X = 6, AB_H = 15, AB_R = 3;
          n.aliases.forEach((a, i) => {
            const abW = ctx.measureText(a).width + AB_PAD_X * 2;
            const abX = n.x + WW_PAD;
            const abY = n.y + WW_PAD + LINE_H * (i + 1) + (LINE_H - AB_H) / 2;
            ctx.beginPath(); _rrect(ctx, abX, abY, abW, AB_H, AB_R);
            ctx.fillStyle = col + '18';
            ctx.fill();
            ctx.strokeStyle = col + '66';
            ctx.lineWidth = 0.5;
            ctx.setLineDash([]);
            ctx.stroke();
            ctx.fillStyle = col + 'bb';
            ctx.fillText(a, abX + AB_PAD_X, abY + AB_H / 2);
          });
        }
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

        // Draw order: container bg → edges → trigger pills → wake boxes (on top)
        built.nodes.filter(n => n.type === 'globals-container').forEach(n => drawGlobalsContainer(n));
        built.nodes.filter(n => n.type === 'ww-container').forEach(n => drawWwContainer(n));
        built.edges.forEach(e => drawEdge(e, dt));
        built.nodes.filter(n => n.type === 'trig' || n.type === 'global').forEach(n => drawTrig(n));
        built.nodes.filter(n => n.type === 'wake').forEach(n => drawWake(n));

        ctx.restore();
        _graphAnimId = requestAnimationFrame(frame);
      }

      canvas.onmousemove = e => {
        const r = canvas.getBoundingClientRect(), mx = e.clientX-r.left, my = e.clientY-r.top;
        hov = null;
        let contHov = null;
        for (const n of built.nodes) {
          if (n.type === 'wake') {
            if (mx >= n.x && mx <= n.x+n.w && my >= n.y && my <= n.y+n.h) { hov = n.id; break; }
          } else if (n.type === 'globals-container' || n.type === 'ww-container') {
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
        if (n.label && n.label.toLowerCase().trim() === norm) {
          _graphFlash(n.id, 2500);
          if (n.type === 'global') _graphFlash('globals-container', 2500);
        }
      }
    }

    function _graphFlashByWord(word) {
      const ms   = ((_cfg?.recognition?.command_timeout || _cfg?.command_timeout || 3) * 1000);
      const norm = word.toLowerCase().trim();
      for (const n of _graphNodes)
        if (n.type === 'wake' && n.label.toLowerCase().trim() === norm) _graphFlash(n.id, ms);
    }

    // ── end graph view ────────────────────────────────────────────────────

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

    function setAudio(connected, connType) {
      // no-op: device labels removed in the panel restructure
    }

    let _lastWake = '';
    let _partialClearTimer = null;

    function _armPartialClear() {
      clearTimeout(_partialClearTimer);
      _partialClearTimer = setTimeout(() => {
        const wave = document.querySelector('#hero .stt-wave');
        if (wave && wave.classList.contains('wv-active')) {
          if (_lastWake === '(reply)') {
            _setHeroContent(_sttWave('wv-listen')
              + '<span class="hero-text"><span class="hero-muted">speak now…</span></span>');
          } else {
            _lastWake = '';
            setStatusListening(false);
            _setHeroContent(_sttWave('wv-idle')
              + '<span class="hero-text hero-muted">…</span>');
          }
        }
      }, 2500);
    }

    function _cancelPartialClear() {
      clearTimeout(_partialClearTimer);
      _partialClearTimer = null;
    }

    function _wakeChip(word, muted) {
      const style = muted ? ' style="opacity:0.45;border-color:var(--skipped);color:var(--skipped)"' : '';
      return '<span class="wake-chip"' + style + '><span class="wake-chip-icon">◉</span>' + esc(word) + '</span>';
    }

    let _heroFadeTimer = null;
    function _setHeroContent(html) {
      const inner = document.querySelector('#hero .hero-inner');
      if (!inner) { document.getElementById('hero').innerHTML = '<span class="hero-inner">' + html + '</span>'; return; }
      clearTimeout(_heroFadeTimer);
      inner.classList.remove('enter');
      inner.classList.add('exit');
      _heroFadeTimer = setTimeout(() => {
        inner.innerHTML = html;
        inner.classList.remove('exit');
        void inner.offsetWidth;
        inner.classList.add('enter');
        _heroFadeTimer = setTimeout(() => inner.classList.remove('enter'), 250);
      }, 160);
    }

    // Update the hero bar in-place with no animation delay — used for
    // partial/transcribing updates so words appear word-by-word in real time.
    function _updateHeroText(waveClass, textHtml) {
      clearTimeout(_heroFadeTimer);
      const hero = document.getElementById('hero');
      let inner = hero.querySelector('.hero-inner');
      if (!inner) {
        hero.innerHTML = '<span class="hero-inner"></span>';
        inner = hero.querySelector('.hero-inner');
      }
      inner.classList.remove('exit', 'enter');
      let wave = inner.querySelector('.stt-wave');
      if (!wave) {
        inner.innerHTML = '<span class="stt-wave ' + waveClass + '">' + _SW + '</span>'
          + '<span class="hero-text"></span>';
        wave = inner.querySelector('.stt-wave');
      } else if (!wave.classList.contains(waveClass)) {
        wave.className = 'stt-wave ' + waveClass;
      }
      const txt = inner.querySelector('.hero-text');
      if (txt) txt.innerHTML = textHtml;
    }

    const _SW = '<span class="sw"></span><span class="sw"></span><span class="sw"></span><span class="sw"></span><span class="sw"></span>';
    function _sttWave(cls) { return '<span class="stt-wave ' + cls + '">' + _SW + '</span>'; }

    function setStt(state, text, m) {
      if (_sttState !== state) {
        _sttState = state;
      }
      const h = document.getElementById('hero');
      h.classList.remove('llm-thinking');
      const sleeping = state === 'sleeping';
      h.classList.toggle('sleeping', sleeping);
      document.body.classList.toggle('stt-sleeping', sleeping);
      switch (state) {
        case 'sleeping':
          _cancelPartialClear();
          var displayText = text || 'Sleeping — say "start listening" to wake';
          _setHeroContent('<span class="hero-icon material-symbols-outlined" style="color:var(--amber)">bedtime</span>'
            + '<span class="hero-text" style="color:var(--amber)">' + esc(displayText) + '</span>');
          break;
        case 'listening':
          _cancelPartialClear();
          clearReplyDim();
          _lastWake = '';
          _setHeroContent(_sttWave('wv-idle')
            + '<span class="hero-text hero-muted"><em>' + (text || 'waiting…') + '</em></span>');
          break;
        case 'transcribing':
          _updateHeroText('wv-active',
            '<span style="color:var(--transcribing)">' + esc(text) + '</span>'
            + '<span class="hero-muted"> …</span>');
          _armPartialClear();
          break;
        case 'direct':
          _cancelPartialClear();
          _lastWake = '';
          _setHeroContent(_sttWave('wv-listen')
            + '<span class="hero-text">'
            + '<span style="font-size:10px;letter-spacing:.06em;color:var(--muted);margin-right:4px">DIRECT</span>'
            + '<span style="color:var(--fg)">' + esc(m.phrase || '') + '</span>'
            + '</span>');
          break;
        case 'wake':
          _cancelPartialClear();
          _lastWake = text;
          if (text === '(reply)') {
            const _phrases = (m.phrases || []);
            const _chips = _phrases.map(p =>
              '<span style="display:inline-block;padding:1px 7px;border-radius:10px;'
              + 'background:rgba(96,165,250,0.15);border:1px solid rgba(96,165,250,0.35);'
              + 'color:#93c5fd;font-size:12px;font-weight:500">' + esc(p) + '</span>'
            ).join('');
            _setHeroContent(_sttWave('wv-listen')
              + '<span class="hero-text">'
              + '<span style="font-size:10px;letter-spacing:.06em;color:var(--muted);margin-right:4px">GRAMMAR</span>'
              + (_chips || '<span class="hero-muted">speak now…</span>')
              + '</span>');
          } else {
            _setHeroContent(_sttWave('wv-listen')
              + '<span class="hero-text">'
              + _wakeChip(text)
              + '<span class="hero-muted">listening…</span>'
              + '</span>');
          }
          break;
        case 'partial':
          _updateHeroText('wv-active',
            (_lastWake && _lastWake !== '(reply)' ? _wakeChip(_lastWake) : '')
            + '<span class="hero-s2">' + esc(text) + '</span>'
            + '<span class="cursor">▋</span>');
          _armPartialClear();
          break;
        case 'matched': {
          _cancelPartialClear();
          const transcript = m.transcript || text;
          const _mWake = (_lastWake && _lastWake !== '(reply)') ? _lastWake : null;
          _setHeroContent('<span class="hero-icon" style="color:var(--match)">✓</span>'
            + '<span class="hero-text">'
            + (_mWake ? _wakeChip(_mWake) : '')
            + (transcript ? '<span style="color:var(--match)">' + esc(transcript) + '</span>' : '')
            + (m.trigger ? '<span class="hero-muted">→</span><span class="hero-trigger">' + esc(m.trigger) + '</span>' : '')
            + '</span>');
          heroAnim('anim-match', 700);
          break;
        }
        case 'nomatch': {
          _cancelPartialClear();
          const _nmWake = (_lastWake && _lastWake !== '(reply)') ? _lastWake : null;
          _setHeroContent('<span class="hero-icon" style="color:var(--nomatch)">✗</span>'
            + '<span class="hero-text">'
            + (_nmWake ? _wakeChip(_nmWake) : '')
            + (text ? '<span style="color:var(--nomatch)">' + esc(text) + '</span>' : '')
            + '<span style="color:var(--nomatch);margin-left:4px">no match</span>'
            + '</span>');
          heroAnim('anim-nomatch', 500);
          break;
        }
        case 'skipped':
          _cancelPartialClear();
          _setHeroContent('<span class="hero-icon" style="color:var(--skipped)">⊘</span>'
            + '<span class="hero-text">'
            + (m.word ? _wakeChip(m.word, true) : '')
            + (text ? '<span style="color:var(--skipped)">' + esc(text) + '</span>' : '')
            + '<span style="color:var(--skipped);margin-left:4px">ignored</span>'
            + '</span>');
          _lastWake = '';
          break;
        case 'gated':
          _cancelPartialClear();
          _setHeroContent('<span class="hero-icon hero-muted">⏸</span>'
            + '<span class="hero-text hero-muted">STT paused during call</span>');
          break;
        case 'llm_thinking': {
          _cancelPartialClear();
          h.classList.add('llm-thinking');
          const transcript = m.transcript || text;
          _setHeroContent('<span class="llm-orb"><span class="hero-icon" style="color:var(--llm)">◈</span>'
            + '<span class="llm-orb-ring"></span></span>'
            + '<span class="hero-text">'
            + (transcript ? '<span style="color:var(--transcribing);font-style:italic">"' + esc(transcript) + '"</span>' : '')
            + '<span class="hero-think-dots">'
            + '<span class="td"></span><span class="td"></span><span class="td"></span>'
            + '</span></span>');
          break;
        }
        case 'llm_reply': {
          heroAnim('anim-llm-reply', 1200);
          const reply = m.reply || text;
          _setHeroContent('<span class="hero-icon" style="color:var(--llm)">◈</span>'
            + '<span class="hero-text" style="color:var(--llm)">' + esc(reply) + '</span>');
          break;
        }
        case 'llm_unreachable':
          _setHeroContent('<span class="hero-icon" style="color:var(--nomatch)">✗</span>'
            + '<span class="hero-text" style="color:var(--nomatch)">remote agent unreachable</span>');
          heroAnim('anim-nomatch', 500);
          break;
        default:
          _setHeroContent('<span class="hero-icon hero-muted">○</span>'
            + '<span class="hero-text hero-muted">STT inactive</span>');
      }
    }

    const MAX_LOG = 1000;
    let logBuffer = [];
    let logRenderTimeout = null;

    function addLog(m) {
      logBuffer.push(m);
      if (!logRenderTimeout) {
        logRenderTimeout = setTimeout(flushLogs, 100);
      }
    }

    function flushLogs() {
      logRenderTimeout = null;
      if (logBuffer.length === 0) return;

      const el = document.getElementById('le');
      if (!el) {
        logBuffer = [];
        return;
      }

      const isAtBottom = el.scrollHeight - el.clientHeight - el.scrollTop < 15;

      const htmls = [];
      for (const m of logBuffer) {
        htmls.push(
          '<div class="le">'
          + '<span class="ts">' + esc(m.ts) + ' </span>'
          + '<span class="' + m.level + '">' + m.level.padEnd(8) + '</span> '
          + esc(m.msg)
          + '</div>'
        );
      }
      logBuffer = [];

      el.insertAdjacentHTML('beforeend', htmls.join(''));

      while (el.children.length > MAX_LOG) {
        el.removeChild(el.firstChild);
      }

      if (isAtBottom) {
        el.scrollTop = el.scrollHeight;
      }
    }

    function clearLogs() {
      logBuffer = [];
      if (logRenderTimeout) {
        clearTimeout(logRenderTimeout);
        logRenderTimeout = null;
      }
      const el = document.getElementById('le');
      if (el) el.innerHTML = '';
    }

    function updateHistoryVisibility() {
      const hl = document.getElementById('hl');
      const empty = document.getElementById('hist-empty');
      if (hl && empty) {
        const hasItems = hl.children.length > 0;
        if (hasItems) {
          hl.style.display = 'block';
          empty.style.display = 'none';
        } else {
          hl.style.display = 'none';
          empty.style.display = 'block';
        }
      }
    }

    function clearHistory() {
      document.getElementById('hl').innerHTML = '';
      updateHistoryVisibility();
      sendCtrl('clear_history');
    }

    function flagFalsePositive(session_id) {
      sendCtrl('flag_fp:' + session_id);
    }

    const MAX_HIST = 60;
    function addSessionHistory(session) {
      if (!session) return;

      const ts = session.timestamp ? new Date(session.timestamp).toTimeString().slice(0, 8) : new Date().toTimeString().slice(0, 8);
      const wakeWord = session.wake ? session.wake.word : '';
      const wakeConf = session.wake && session.wake.confidence != null ? ' <span class="hscore" style="opacity:0.6;font-size:9px;">(' + Math.round(session.wake.confidence * 100) + '%)</span>' : '';

      let bodyHtml = '';

      if (session.transcript) {
        const text = session.transcript.text;
        const isMatched = session.transcript.is_matched;
        const gated = session.diagnostics && session.diagnostics.gated;
        const timeout = session.transcript.timeout;

        if (gated) {
          bodyHtml += '<div class="he-mid"><span class="hcmd" style="color:var(--muted);font-style:italic;">[Noise/Silence Gated]</span></div>';
        } else if (text) {
          bodyHtml += '<div class="he-mid"><span class="hcmd">"' + esc(text) + '"</span></div>';
        } else if (timeout) {
          bodyHtml += '<div class="he-mid"><span class="hcmd" style="color:var(--muted);font-style:italic;">[Response Timeout]</span></div>';
        } else {
          bodyHtml += '<div class="he-mid"><span class="hcmd" style="color:var(--muted);font-style:italic;">[Silence]</span></div>';
        }

        if (session.transcript.match_phrase) {
          const matchPhrase = session.transcript.match_phrase;
          const score = session.transcript.match_score;
          const scoreStr = score != null ? ' <span class="hscore" style="opacity:0.7;font-weight:normal;margin-left:4px;">(' + Math.round(score) + '%)</span>' : '';

          bodyHtml += '<div class="he-bot"><span class="htrig">' + esc(matchPhrase) + scoreStr + '</span></div>';
        } else if (!isMatched && text) {
          bodyHtml += '<div class="he-bot"><span class="hnomatch">✗ no match</span></div>';
        }
      }

      if (session.llm && session.llm.reply) {
        bodyHtml += '<div class="hllm-reply" style="margin-top:2px;font-size:10px;color:var(--info);opacity:0.9;">💬 ' + esc(session.llm.reply) + '</div>';
      }

      const session_id = session.session_id;
      const isFp = session.feedback && session.feedback.false_positive;

      let actionBtnHtml = '';
      if (isFp) {
        actionBtnHtml = '<span class="hflagged" style="font-size:9px;color:var(--nomatch);font-weight:bold;margin-left:auto;">⚠️ Flagged</span>';
      } else if (session_id) {
        actionBtnHtml = '<button class="hflag-btn" onclick="flagFalsePositive(\'' + esc(session_id) + '\')" style="margin-left:auto;font-size:9px;background:rgba(255,255,255,0.06);border:1px solid var(--border);border-radius:4px;color:var(--muted);padding:1px 5px;cursor:pointer;">Flag FP</button>';
      }

      const itemHtml = '<div class="he-top">'
        + (wakeWord ? '<span class="hwk">' + esc(wakeWord) + wakeConf + '</span>' : '<span></span>')
        + '<span class="hts">' + ts + '</span>'
        + '</div>'
        + bodyHtml
        + '<div class="he-action-row" style="display:flex;align-items:center;margin-top:2px;">'
        + actionBtnHtml
        + '</div>';

      const el = document.getElementById('hl');
      if (!el) return;
      const d = document.createElement('div');
      d.className = 'he' + (isFp ? ' fp-flagged' : '');
      d.setAttribute('data-id', session_id);
      d.innerHTML = itemHtml;

      el.insertBefore(d, el.firstChild);
      while (el.children.length > MAX_HIST) el.removeChild(el.lastChild);
      updateHistoryVisibility();
    }

    function sendCtrl(action) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({type: 'control', action}));
    }

    function esc(s) {
      return String(s)
        .replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function applyTheme(theme) {
      if (theme === 'light') {
        document.documentElement.setAttribute('data-theme', 'light');
      } else {
        document.documentElement.removeAttribute('data-theme');
      }
      const btn = document.getElementById('btn-theme');
      if (btn) btn.textContent = theme === 'light' ? 'dark_mode' : 'light_mode';
    }

    function _morphIcons(fromIcon, toIcon, applyFn) {
      const overlay = document.getElementById('morph-overlay');
      overlay.innerHTML = '<span class="morph-icon morph-out material-symbols-outlined">' + fromIcon + '</span><span class="morph-icon morph-in material-symbols-outlined">' + toIcon + '</span>';
      overlay.classList.remove('active');
      void overlay.offsetWidth;
      overlay.classList.add('active');
      setTimeout(() => {
        applyFn();
        overlay.classList.remove('active');
        overlay.innerHTML = '';
      }, 450);
    }

    function toggleTheme() {
      const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      const next = current === 'light' ? 'dark' : 'light';
      const fromIcon = current === 'light' ? 'light_mode' : 'dark_mode';
      const toIcon = next === 'light' ? 'dark_mode' : 'light_mode';
      _morphIcons(fromIcon, toIcon, () => {
        localStorage.setItem('theme', next);
        applyTheme(next);
      });
    }

    // ── mode toggle ──────────────────────────────────────────────────────────
    function applyMode(mode) {
      const body = document.body;
      if (mode === 'dev') {
        body.classList.add('dev-mode');
      } else {
        body.classList.remove('dev-mode');
      }
      const btn = document.getElementById('btn-mode');
      if (btn) btn.textContent = mode === 'dev' ? 'person' : 'code';
      localStorage.setItem('dashboard-mode', mode);
    }

    function toggleMode() {
      const current = document.body.classList.contains('dev-mode') ? 'dev' : 'user';
      const next = current === 'dev' ? 'user' : 'dev';
      const fromIcon = current === 'dev' ? 'person' : 'code';
      const toIcon = next === 'dev' ? 'person' : 'code';
      _morphIcons(fromIcon, toIcon, () => applyMode(next));
    }

    function toggleMonitor() {
      const sec = document.getElementById('monitoring-section');
      const collapsed = sec.classList.toggle('collapsed');
      localStorage.setItem('monitor-collapsed', collapsed ? '1' : '0');
    }

    function toggleHistory() {
      const sec = document.getElementById('history-section');
      const collapsed = sec.classList.toggle('collapsed');
      localStorage.setItem('history-collapsed', collapsed ? '1' : '0');
    }

    function toggleLog() {
      const sec = document.getElementById('log-panel');
      const collapsed = sec.classList.toggle('collapsed');
      localStorage.setItem('log-collapsed', collapsed ? '1' : '0');
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

    // ── init ──────────────────────────────────────────────────────────────────
    (function() {
      const theme = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      const btn = document.getElementById('btn-theme');
      if (btn) btn.textContent = theme === 'light' ? '🌙' : '☀';
      const savedMode = localStorage.getItem('dashboard-mode') || 'user';
      applyMode(savedMode);
      if (localStorage.getItem('monitor-collapsed') === '1') {
        const sec = document.getElementById('monitoring-section');
        if (sec) sec.classList.add('collapsed');
      }
      if (localStorage.getItem('log-collapsed') === '1') {
        const sec = document.getElementById('log-panel');
        if (sec) sec.classList.add('collapsed');
      }
      updateHistoryVisibility();
    })();

    connect();

    // Follow OS preference changes unless user has a stored override
    matchMedia('(prefers-color-scheme: light)').addEventListener('change', function(e) {
      if (!localStorage.getItem('theme')) applyTheme(e.matches ? 'light' : 'dark');
    });


    function showToast(message, type = 'info') {
      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.textContent = message;
      toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        background: ${type === 'error' ? 'rgba(248,113,113,0.95)' : type === 'success' ? 'rgba(74,222,128,0.95)' : 'rgba(96,165,250,0.95)'};
        color: #000;
        padding: 12px 24px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        z-index: 2000;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        animation: slideUp 0.3s ease-out;
        max-width: 90%;
        text-align: center;
      `;
      document.body.appendChild(toast);
      setTimeout(() => {
        toast.style.animation = 'slideDown 0.3s ease-in';
        setTimeout(() => toast.remove(), 300);
      }, 3000);
    }

    let currentConfig = null;
    let originalConfig = null;

    function openConfigModal() {
      const modal = document.getElementById('config-modal');
      modal.classList.remove('hidden');

      fetch('/api/config')
        .then(response => response.json())
        .then(config => {
          currentConfig = config;
          originalConfig = JSON.parse(JSON.stringify(config));
          renderConfigForm(config);
        })
        .catch(() => {
          showToast('Failed to load configuration', 'error');
        });
    }

    function closeConfigModal() {
      const modal = document.getElementById('config-modal');
      modal.classList.add('hidden');
      currentConfig = null;
      originalConfig = null;
    }

    function resetConfigForm() {
      if (!confirm('Reset alla configurazione predefinita? I valori correnti verranno persi.')) return;
      fetch('/api/config/defaults')
        .then(response => response.json())
        .then(config => {
          currentConfig = config;
          renderConfigForm(currentConfig);
          showToast('Moduli reimpostati ai valori predefiniti', 'info');
        })
        .catch(() => {
          showToast('Errore nel caricamento dei valori predefiniti', 'error');
        });
    }

    function removeWakeWord(index) {
      if (!currentConfig.wake_words) return;
      currentConfig.wake_words.splice(index, 1);
      renderConfigForm(currentConfig);
    }

    async function saveConfig() {
      if (!currentConfig) return;

      const saveBtn = document.querySelector('#config-modal .modal-footer button:last-child');
      const originalText = saveBtn.textContent;
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';

      const formData = collectFormData();
      const response = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      const data = await response.json();
      saveBtn.disabled = false;
      saveBtn.textContent = originalText;

      if (response.ok) {
        showToast('Configuration saved! Restarting...', 'success');
        closeConfigModal();
        sendCtrl('restart');
      } else {
        showToast('Failed: ' + (data.error || 'Unknown error'), 'error');
      }
    }

    function renderWakeWordsList() {
      if (!currentConfig.wake_words || currentConfig.wake_words.length === 0) {
        return '<p style="color: var(--muted); font-size: 13px;">No wake words configured</p>';
      }

      let html = '<div style="display: flex; flex-direction: column; gap: 8px;">';
      currentConfig.wake_words.forEach((ww, index) => {
        const skipBadge = ww.skip_unmatched_inline
          ? `<span class="ww-skip-badge" title="Standalone wake with no inline command is silently ignored"><span class="ww-skip-badge-icon">⊘</span>skip unmatched</span>`
          : '';
        html += `
          <div style="display: flex; align-items: center; gap: 8px; background: var(--surface); padding: 8px; border-radius: 6px; border: 1px solid var(--border);">
            <span style="color: var(--info); font-weight: 500;">${ww.word}</span>
            ${ww.aliases && ww.aliases.length > 0 ? `<span style="font-size: 12px; color: var(--muted);">(${ww.aliases.join(', ')})</span>` : ''}
            ${skipBadge}
            <button onclick="removeWakeWord(${index})" style="margin-left: auto; background: rgba(248,113,113,0.2); border: none; color: #f87171; padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 12px;">✕</button>
          </div>
        `;
      });
      html += '</div>';
      return html;
    }

    function renderConfigForm(config) {
      const container = document.getElementById('config-form');
      container.innerHTML = '';

      container.innerHTML += `
        <div class="form-section">
          <h3>Wake Words</h3>
          <div class="form-group">
            <label>Wake Word Groups</label>
            <div id="wake-words-list" style="margin-bottom: 12px;"></div>
            <div style="display: flex; gap: 8px;">
              <input type="text" id="new-wake-word" placeholder="Add new wake word..." style="flex: 1; padding: 8px 12px; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-size: 14px;">
              <button onclick="addWakeWord()" style="background: var(--info); border: none; color: #000; padding: 8px 16px; border-radius: 6px; cursor: pointer;">Add</button>
            </div>
          </div>
        </div>
      `;

      document.getElementById('wake-words-list').innerHTML = renderWakeWordsList();

      container.innerHTML += `
        <div class="form-section">
          <h3>Recognition</h3>
          <div class="form-group">
            <label>Command Timeout (seconds)</label>
            <input type="number" id="input-command-timeout" step="0.1" min="0.1">
          </div>
          <div class="form-group">
            <label>Matching Threshold (%)</label>
            <input type="number" id="input-matching-threshold" step="1" min="0" max="100">
          </div>
          <div class="form-group">
            <label>Matching Algorithm</label>
            <select id="input-matching-algorithm">
              <option value="token_set_ratio">token_set_ratio</option>
              <option value="levenshtein">levenshtein</option>
              <option value="ratio">ratio</option>
            </select>
          </div>
          <div class="form-group">
            <label>Partial Matching</label>
            <select id="input-partial-matching">
              <option value="true">Enabled</option>
              <option value="false">Disabled</option>
            </select>
          </div>
          <div class="form-group">
            <label>Reply Matching Algorithm <span class="form-hint" style="display:inline">(ask action)</span></label>
            <select id="input-reply-matching-algorithm">
              <option value="levenshtein">levenshtein</option>
              <option value="token_set_ratio">token_set_ratio</option>
              <option value="ratio">ratio</option>
            </select>
          </div>
          <div class="form-group">
            <label>Reply Matching Threshold (%) <span class="form-hint" style="display:inline">(ask action)</span></label>
            <input type="number" id="input-reply-matching-threshold" step="1" min="0" max="100">
          </div>
          <div class="form-group">
            <label>Follow-up Mode</label>
            <select id="input-follow-up">
              <option value="false">Disabled</option>
              <option value="true">Enabled</option>
            </select>
            <span class="form-hint">Continue conversation after a trigger fires</span>
          </div>
          <div class="form-group">
            <label>Follow-up Timeout (seconds)</label>
            <input type="number" id="input-follow-up-timeout" step="0.5" min="0.5">
          </div>
          <div class="form-group">
            <label>Follow-up Max Turns</label>
            <input type="number" id="input-follow-up-max-turns" step="1" min="1" max="20">
          </div>
        </div>
      `;

      container.innerHTML += `
        <div class="form-section">
          <h3>Speech-to-Text</h3>
          <div class="form-group">
            <label>Backend</label>
            <select id="input-stt-backend">
              <option value="vosk">vosk</option>
              <option value="sherpa-onnx">sherpa-onnx</option>
            </select>
          </div>
          <div class="form-group">
            <label>Stage 1 Confidence</label>
            <input type="number" id="input-stt-confidence" step="0.01" min="0" max="1">
          </div>
        </div>
      `;

      container.innerHTML += `
        <div class="form-section">
          <h3>Microfono</h3>
          <div class="form-group">
            <label>Output Volume (0–1)</label>
            <input type="number" id="input-output-volume" step="0.05" min="0" max="1">
            <span class="form-hint">Volume altoparlante (0 = muto, 1 = massimo)</span>
          </div>
          <div class="form-group">
            <label>Input Gain (× moltiplicatore)</label>
            <input type="number" id="input-input-gain" step="0.1" min="0" max="10" value="1.0">
            <span class="form-hint">1.0 = normale, 2.0 = doppio volume</span>
          </div>
          <div class="form-group">
            <label>Soglia Silenzio (RMS fisso)</label>
            <input type="number" id="input-rms-threshold" step="0.01" min="0" max="1" value="0.02">
            <span class="form-hint">Più basso = più sensibile (0.02 default)</span>
          </div>
          <div class="form-group">
            <label>Adattamento Rumore di Fondo (RMS Adattivo)</label>
            <select id="input-adaptive-rms">
              <option value="true">Abilita (sovrascrive RMS fisso)</option>
              <option value="false">Disabilita</option>
            </select>
            <span class="form-hint">Regola automaticamente la soglia in base al rumore della stanza.</span>
          </div>
        </div>
      `;

      container.innerHTML += `
        <div class="form-section">
          <h3>Text-to-Speech</h3>
          <div class="form-group">
            <label>Backend</label>
            <select id="input-tts-backend">
              <option value="piper">piper</option>
              <option value="pico">pico</option>
            </select>
          </div>
          <div class="form-group">
            <label>Voice</label>
            <select id="input-tts-voice">
              <option value="it_IT-paola-medium">Paola (donna)</option>
              <option value="it_IT-riccardo-x_low">Riccardo (uomo)</option>
            </select>
          </div>
        </div>
      `;

      document.getElementById('input-command-timeout').value = config.recognition?.command_timeout ?? '';
      document.getElementById('input-matching-threshold').value = config.recognition?.matching_threshold ?? '';
      document.getElementById('input-matching-algorithm').value = config.recognition?.matching_algorithm || 'token_set_ratio';
      document.getElementById('input-partial-matching').value = config.recognition?.partial_matching !== false ? 'true' : 'false';
      document.getElementById('input-reply-matching-algorithm').value = config.recognition?.reply_matching_algorithm || 'levenshtein';
      document.getElementById('input-reply-matching-threshold').value = config.recognition?.reply_matching_threshold ?? '';
      document.getElementById('input-follow-up').value = config.recognition?.follow_up ? 'true' : 'false';
      document.getElementById('input-follow-up-timeout').value = config.recognition?.follow_up_timeout ?? '';
      document.getElementById('input-follow-up-max-turns').value = config.recognition?.follow_up_max_turns ?? '';
      document.getElementById('input-stt-backend').value = config.stt?.stage1?.backend || 'vosk';
      document.getElementById('input-stt-confidence').value = config.stt?.stage1?.confidence ?? '';
      document.getElementById('input-rms-threshold').value = config.stt?.stage1?.rms_threshold ?? '';
      document.getElementById('input-adaptive-rms').value = config.stt?.stage1?.adaptive_rms !== false ? 'true' : 'false';
      document.getElementById('input-output-volume').value = config.audio?.output_volume ?? '';
      document.getElementById('input-input-gain').value = config.audio?.input_gain ?? '';
      document.getElementById('input-tts-backend').value = config.tts?.backend || 'piper';
      document.getElementById('input-tts-voice').value = config.tts?.voice || '';
    }

    function addWakeWord() {
      const input = document.getElementById('new-wake-word');
      const word = input.value.trim();
      if (!word) return;

      if (!currentConfig.wake_words) {
        currentConfig.wake_words = [];
      }

      currentConfig.wake_words.push({
        word: word,
        aliases: []
      });

      input.value = '';
      renderConfigForm(currentConfig);
    }

    function collectFormData() {
      const result = { wake_words: (currentConfig.wake_words || []).map(w => ({ word: w.word, aliases: w.aliases || [] })) };

      const commandTimeout = parseFloat(document.getElementById('input-command-timeout').value);
      if (!isNaN(commandTimeout)) {
        result.recognition = {
          command_timeout: commandTimeout,
          matching_algorithm: document.getElementById('input-matching-algorithm').value,
          partial_matching: document.getElementById('input-partial-matching').value === 'true',
          reply_matching_algorithm: document.getElementById('input-reply-matching-algorithm').value,
          follow_up: document.getElementById('input-follow-up').value === 'true',
        };
        // Only include numeric fields if they parse — NaN serializes to JSON null
        // which breaks the daemon's float() coercion on cold start.
        const matchingThreshold = parseFloat(document.getElementById('input-matching-threshold').value);
        if (!isNaN(matchingThreshold)) result.recognition.matching_threshold = matchingThreshold;
        const replyThreshold = parseFloat(document.getElementById('input-reply-matching-threshold').value);
        if (!isNaN(replyThreshold)) result.recognition.reply_matching_threshold = replyThreshold;
        const followUpTimeout = parseFloat(document.getElementById('input-follow-up-timeout').value);
        if (!isNaN(followUpTimeout)) result.recognition.follow_up_timeout = followUpTimeout;
        const followUpMaxTurns = parseInt(document.getElementById('input-follow-up-max-turns').value, 10);
        if (!isNaN(followUpMaxTurns)) result.recognition.follow_up_max_turns = followUpMaxTurns;
      }

      const confidence = parseFloat(document.getElementById('input-stt-confidence').value);
      if (!isNaN(confidence)) {
        result.stt = {
          stage1: {
            backend: document.getElementById('input-stt-backend').value,
            confidence: confidence,
            adaptive_rms: document.getElementById('input-adaptive-rms').value === 'true',
          }
        };
        const rmsThreshold = parseFloat(document.getElementById('input-rms-threshold').value);
        if (!isNaN(rmsThreshold)) result.stt.stage1.rms_threshold = rmsThreshold;
      }

      result.audio = {};
      const outputVolume = parseFloat(document.getElementById('input-output-volume').value);
      if (!isNaN(outputVolume)) result.audio.output_volume = outputVolume;
      const inputGain = parseFloat(document.getElementById('input-input-gain').value);
      if (!isNaN(inputGain)) result.audio.input_gain = inputGain;
      if (!Object.keys(result.audio).length) delete result.audio;

      const ttsBackend = document.getElementById('input-tts-backend').value;
      if (ttsBackend) {
        result.tts = {
          backend: ttsBackend,
          voice: document.getElementById('input-tts-voice').value
        };
      }

      return result;
    }