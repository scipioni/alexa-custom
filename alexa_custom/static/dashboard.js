// build vertical segmented VU meters
    ['mic-segs-v', 'spk-segs-v'].forEach(id => {
      const c = document.getElementById(id);
      for (let i = 0; i < 20; i++) {
        const s = document.createElement('span');
        s.className = 'seg-v';
        c.appendChild(s);
      }
    });

    let ws = null, reconnTimer = null, _restarting = false, _reconnDelay = 1000, reconnectPopupTimer = null;
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
      ws.onmessage = (e) => { try { handle(JSON.parse(e.data)); } catch(err) { console.error('WS message error:', err); } };
    }

    function wsInd(up) {
      const el = document.getElementById('ws-ind');
      el.textContent = up ? 'WS connected' : 'WS reconnecting…';
      el.className   = up ? 'ok' : '';
      const dot = document.getElementById('cdot');
      dot.className = up ? 'sdot ok' : 'sdot warn';

      const popup = document.getElementById('reconnect-popup');
      if (popup) {
        if (up) {
          if (reconnectPopupTimer) {
            clearTimeout(reconnectPopupTimer);
            reconnectPopupTimer = null;
          }
          popup.classList.add('hidden');
        } else {
          if (popup.classList.contains('hidden') && !reconnectPopupTimer) {
            reconnectPopupTimer = setTimeout(() => {
              popup.classList.remove('hidden');
              reconnectPopupTimer = null;
            }, 500);
          }
        }
      }
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
            document.getElementById('hl').innerHTML = '';
            m.history.forEach(addSessionHistory);
          }
          if (m.system) updateSparkline(m.system);
          if (m.volume != null) initVolumeSlider(m.volume);
          break;
        }
        case 'participant_joined':
          parts[m.participant.identity] = m.participant.tracks;
          renderParts(); break;
        case 'participant_left':
          delete parts[m.identity];
          renderParts(); break;
        case 'track_published':
        case 'track_unpublished':
        case 'track_subscribed':
        case 'track_unsubscribed':
          if (m.identity in parts) parts[m.identity] = Math.max(0, (parts[m.identity]||1)-1);
          renderParts(); break;
        case 'volume_update': {
          setVU('mic', m.mic||0); setVU('spk', m.spk||0);

          if (m.adaptive) {
            const rmsLine = document.getElementById('mic-rms-line');
            if (rmsLine) rmsLine.classList.add('adaptive');
          } else {
            const rmsLine = document.getElementById('mic-rms-line');
            if (rmsLine) rmsLine.classList.remove('adaptive');
          }
          break;
        }
        case 'audio_connect':
          setAudio(true, m.conn_type); break;
        case 'audio_disconnect':
          setAudio(false, null); break;
        case 'room_status':
          setRoomStatus(m.status, m.timeout || 0);
          break;
        case 'stt_update': {
          let s = m.stt_state;
          const isFinished = s !== 'wake' && s !== 'partial' && s !== 'transcribing';
          if (s === 'reply') {
            const trigs = document.querySelectorAll('.htrig, .hnomatch');
            if (trigs.length) trigs[0].scrollIntoView({behavior: 'smooth', block: 'nearest'});
          }
          if (s === 'match' || s === 'nomatch') {
            const word = _lastWakeWord;
            const text = m.text || m.word || m.transcript || '';
            updateInteraction(word, text, isFinished);
            _lastWakeWord = '';
          }
          if (s === 'wake') {
            _lastWakeWord = m.word || '';
            updateInteraction(_lastWakeWord, '', isFinished);
          }
          setStt(s, m.text||m.word||m.transcript||m.reply||'', m);
          break;
        }
        case 'log':       addLog(m); break;
        case 'restarting': {
          _restarting = true;
          const b = document.getElementById('btn-restart');
          if (b) { b.disabled = true; b.classList.add('spinning'); }
          setSt('Restarting server…', null);
          break;
        }
        case 'actions_config':
          _cfg = m.config;
          renderActions(_cfg);
          break;
        case 'system_update':
          updateSparkline(m.system);
          break;
        case 'volume_set':
          initVolumeSlider(m.volume);
          break;
        case 'session_history':
          addSessionHistory(m.session);
          break;
        case 'toast':
          showToast(m.message, m.level || 'info');
          break;
      }
    }

    // ── room state donut ───────────────────────────────────────────────────
    let donutTimer = null, donutEnd = 0, donutDur = 0;
    function _updateDonut() {
      const el = document.getElementById('room-donut');
      if (!el) return;
      const rem = donutEnd - performance.now();
      if (rem <= 0) { _hideDonut(); return; }
      const p = rem / donutDur;
      // perimeter of R=15 circle is 2*PI*15 = 94.248
      const offset = 94.248 * (1 - p);
      el.style.strokeDashoffset = offset.toFixed(2);
      donutTimer = requestAnimationFrame(_updateDonut);
    }
    function _showDonut(timeout) {
      if (donutTimer) cancelAnimationFrame(donutTimer);
      const el = document.getElementById('room-donut-wrap');
      if (el) el.style.display = 'block';
      donutDur = timeout * 1000;
      donutEnd = performance.now() + donutDur;
      _updateDonut();
    }
    function _hideDonut() {
      if (donutTimer) cancelAnimationFrame(donutTimer);
      donutTimer = null;
      const el = document.getElementById('room-donut-wrap');
      if (el) el.style.display = 'none';
    }
    function _checkRoomConfig(m) {
      const llm = m.llm_config;
      const el  = document.getElementById('ai-section');
      if (el) {
        el.style.display = llm && llm.enabled ? 'block' : 'none';
        const modelEl = document.getElementById('llm-model-name');
        if (modelEl) modelEl.textContent = llm.model.split('/').pop();
      }
    }

    function setRoomStatus(status, timeout) {
      const room = document.getElementById('room-status-body');
      const icon = document.getElementById('rs-icon');
      const lbl  = document.getElementById('rs-lbl');
      if (!room || !icon || !lbl) return;

      room.className = 'rstatus-' + status;
      if (status === 'closed') {
        icon.textContent = 'phone_disabled'; lbl.textContent = 'Chiamata terminata';
        _hideDonut();
      } else if (status === 'ringing') {
        icon.textContent = 'ring_volume'; lbl.textContent = 'In arrivo…';
        if (timeout > 0) _showDonut(timeout); else _hideDonut();
      } else if (status === 'talking') {
        icon.textContent = 'phone_in_talk'; lbl.textContent = 'In conversazione';
        _hideDonut();
      } else if (status === 'answering') {
        icon.textContent = 'quickreply'; lbl.textContent = 'Risposta in corso…';
        _hideDonut();
      }
    }

    function setLlmBadgeThinking(on) {
      const badge = document.getElementById('llm-model-name');
      if (badge) badge.classList.toggle('thinking', on);
    }

    function setLlmStatusDot(thinking) {
      const badge = document.getElementById('llm-model-name');
      if (badge) badge.innerHTML = thinking ? '<span class="llm-dot"></span><span class="llm-dot"></span><span class="llm-dot"></span>' : '';
    }

    function heroAnim(cls, duration) {
      const el = document.querySelector('#hero .stt-wave');
      if (!el) return;
      el.className = 'stt-wave ' + cls;
      clearTimeout(_heroTimers[cls]);
      if (duration) {
        _heroTimers[cls] = setTimeout(() => el.classList.remove(cls), duration);
      }
    }

    function _trigPhrase(el) {
      const phrase = el.querySelector('.tphrase').textContent.trim();
      _graphFlashByPhrase(phrase);
    }

    function highlightTrigger(phrase, isReply) {
      if (!phrase) return;
      const norm = phrase.toLowerCase().trim();
      const items = document.querySelectorAll(isReply ? '.abranches .abranch' : '#ww-tree-body .tcard');
      items.forEach(el => {
        const txt = el.querySelector(isReply ? '.abranch-lbl' : '.tphrase').textContent.toLowerCase().trim();
        if (txt === norm) {
          el.classList.add('flash-active');
          setTimeout(() => el.classList.remove('flash-active'), 2500);
        }
      });
      _graphFlashByPhrase(phrase);
    }

    function dimNonMatchingReplies(partial) {
      if (!partial) return;
      const norm = partial.toLowerCase().trim();
      const branches = document.querySelectorAll('.abranches .abranch');
      let matchedAny = false;
      branches.forEach(el => {
        const txt = el.querySelector('.abranch-lbl').textContent.toLowerCase().trim();
        const score = txt.includes(norm) || norm.includes(txt);
        el.classList.toggle('dimmed', !score);
        if (score) matchedAny = true;
      });
      if (matchedAny) {
        clearTimeout(_heroTimers.replyDimClear);
      }
    }

    function clearReplyDim() {
      document.querySelectorAll('.abranches .abranch').forEach(el => el.classList.remove('dimmed'));
    }

    function updateInteraction(word, text, finish) {
      const wrap = document.getElementById('interact-wrap');
      if (!wrap) return;
      if (!word && !text) {
        wrap.classList.add('hidden');
        return;
      }
      wrap.classList.remove('hidden');
      document.getElementById('int-wake').textContent = word || '—';
      document.getElementById('int-cmd').textContent = text ? '"' + text + '"' : 'listening…';
      document.getElementById('int-cmd').classList.toggle('hero-muted', !text);
      if (finish) {
        setTimeout(() => wrap.classList.add('hidden'), 5000);
      }
    }

    function setSt(_text, room) {
      const el = document.getElementById('st');
      if (el) el.textContent = _text;
      if (room != null) {
        const r = document.getElementById('room');
        if (r) r.textContent = room ? ' #' + room : '';
      }
    }

    function setStatusListening(listening) {
      const dot = document.getElementById('cdot');
      if (listening) {
        dot.className = 'sdot ok';
        dot.style.boxShadow = '0 0 10px #4ade80';
      } else {
        dot.className = ws && ws.readyState === WebSocket.OPEN ? 'sdot ok' : 'sdot warn';
        dot.style.boxShadow = '';
      }
    }

    function renderParts() {
      const el = document.getElementById('parts-list');
      if (!el) return;
      el.innerHTML = '';
      const list = Object.entries(parts).map(([identity, tracks]) => {
        const isMe = identity === 'local' || identity.startsWith('client-') || identity.includes('alexa');
        const role = isMe ? 'me' : 'remote';
        const icon = isMe ? 'person' : 'record_voice_over';
        const label = identity;
        const state = tracks > 0 ? 'speaking' : 'silent';
        return `<div class="part-chip ${role} ${state}"><span class="material-symbols-outlined">${icon}</span>${label}</div>`;
      });
      if (list.length === 0) {
        el.innerHTML = '<div style="padding: 16px 12px; font-size: 11px; color: var(--muted); text-align: center; font-style: italic;">No active participants</div>';
      } else {
        el.innerHTML = list.join('');
      }
    }

    function _aliases(list) {
      return (list||[]).map(a => `<div class="talias"><span class="arr">└</span>${esc(a)}</div>`).join('');
    }

    function _actionBadge(label) {
      return `<span class="act-badge">${esc(label)}</span>`;
    }

    function _badges(actions) {
      const list = [];
      (actions||[]).forEach(a => {
        if (a.type === 'say') list.push(_actionBadge('🗣️ ' + a.params?.text));
        if (a.type === 'shell') list.push(_actionBadge('🖥️ ' + a.params?.cmd));
        if (a.type === 'mqtt') list.push(_actionBadge('📡 mqtt'));
        if (a.type === 'telegram') list.push(_actionBadge('📱 telegram'));
        if (a.type === 'tone') list.push(_actionBadge('🎵 tone'));
      });
      return list.join(' ');
    }

    function renderTrigTree(actions) {
      const el = document.getElementById('ww-tree-body');
      if (!el) return;
      el.innerHTML = '';
      const list = (actions.triggers||[]).map(t => {
        const ph = t.phrase;
        const aliases = _aliases(t.aliases);
        const badges = _badges(t.actions);
        const ask = (t.actions||[]).find(a => a.type === 'ask');
        let askHtml = '';
        if (ask) {
          const qText = ask.params?.text || '';
          let bHtml = '';
          (ask.on_reply||[]).forEach(r => {
            const rBadges = _badges(r.actions);
            bHtml += `<div class="abranch"><span class="abranch-line">├</span><span class="abranch-lbl">${esc(r.phrase)}</span>${rBadges}</div>`;
          });
          askHtml = `<div class="ask-card"><div class="aq">🗣️ "${esc(qText)}"</div><div class="abranches">${bHtml}</div></div>`;
        }
        return `<div class="tcard" onclick="_trigPhrase(this)"><div class="tcard-top"><span class="tphrase">${esc(ph)}</span>${badges}</div>${aliases}${askHtml}</div>`;
      });
      if (list.length === 0) {
        el.innerHTML = '<div style="padding: 16px 12px; font-size: 11px; color: var(--muted); text-align: center; font-style: italic;">No triggers loaded</div>';
      } else {
        el.innerHTML = list.join('');
      }
    }

    function renderActions(cfg) {
      renderTrigTree(cfg);
      if (_graphViewInited || (cfg && cfg.triggers && cfg.triggers.length > 0)) {
        _graphViewInited = true;
        renderGraph(cfg);
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
    }

    function _wakeChip(word, muted) {
      const cls = muted ? 'ww-chip ww-muted' : 'ww-chip';
      return `<span class="${cls}"><span class="material-symbols-outlined font-sm">bolt</span>${esc(word)}</span>`;
    }

    function _setHeroContent(html) {
      const el = document.getElementById('hero');
      if (el) {
        el.innerHTML = '<span class="hero-inner">' + html + '</span>';
      }
    }

    function _updateHeroText(waveClass, textHtml) {
      _setHeroContent(_sttWave(waveClass) + '<span class="hero-text">' + textHtml + '</span>');
    }

    const _SW = '<span class="sw"></span><span class="sw"></span><span class="sw"></span><span class="sw"></span><span class="sw"></span>';
    function _sttWave(cls) { return '<span class="stt-wave ' + cls + '">' + _SW + '</span>'; }

    function setStt(state, text, m) {
      _sttState = state;
      _cancelPartialClear();

      const modelEl = document.getElementById('llm-model-name');
      const aiEl = document.getElementById('ai-section');

      if (state === 'idle') {
        _lastWake = '';
        setStatusListening(false);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        _updateHeroText('wv-idle', '<span class="hero-muted">STT inactive</span>');
      } else if (state === 'listening') {
        _lastWake = '';
        setStatusListening(false);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        _updateHeroText('wv-idle', '<span class="hero-muted">…</span>');
      } else if (state === 'wake') {
        _lastWake = text;
        setStatusListening(true);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        _setHeroContent(_sttWave('wv-active') + _wakeChip(text, false) + '<span class="hero-text"><span class="hero-muted">listening…</span></span>');
        _graphFlashByWord(text);
      } else if (state === 'partial') {
        const textHtml = _lastWake ? _wakeChip(_lastWake, true) + ' ' + esc(text) : esc(text);
        setStatusListening(true);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        _updateHeroText('wv-active', textHtml);
        if (_lastWake === '(reply)') {
          dimNonMatchingReplies(text);
        }
      } else if (state === 'transcribing') {
        setStatusListening(true);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        _updateHeroText('wv-active', '<span class="hero-muted">elaborazione…</span>');
      } else if (state === 'match') {
        _lastWake = '';
        setStatusListening(false);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        _updateHeroText('wv-success', esc(text));
        heroAnim('wv-success', 1500);
        highlightTrigger(text, false);
      } else if (state === 'match_reply') {
        _lastWake = '';
        setStatusListening(false);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        clearReplyDim();
        _updateHeroText('wv-success', esc(text));
        heroAnim('wv-success', 1500);
        highlightTrigger(text, true);
      } else if (state === 'nomatch') {
        _lastWake = '';
        setStatusListening(false);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        clearReplyDim();
        _updateHeroText('wv-error', esc(text || '✗ comando non riconosciuto'));
        heroAnim('wv-error', 1500);
      } else if (state === 'reply') {
        _lastWake = '(reply)';
        setStatusListening(true);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        _setHeroContent(_sttWave('wv-listen') + '<span class="hero-text"><span class="hero-muted">speak now…</span></span>');
        _armPartialClear();
      } else if (state === 'llm_thinking') {
        setStatusListening(false);
        setLlmBadgeThinking(true);
        setLlmStatusDot(true);
        _updateHeroText('wv-thinking', '<span style="color:var(--llm);">AI Fallback…</span>');
        if (aiEl) {
          aiEl.style.display = 'block';
          const content = document.getElementById('ai-content');
          if (content) content.innerHTML = '<span style="color:var(--muted); font-style:italic">Generazione risposta in corso...</span>';
        }
      } else if (state === 'llm_reply') {
        setStatusListening(false);
        setLlmBadgeThinking(false);
        setLlmStatusDot(false);
        _updateHeroText('wv-success', '<span style="color:var(--llm);">AI Fallback completato</span>');
        heroAnim('wv-success', 1500);
        if (aiEl && m && m.reply) {
          aiEl.style.display = 'block';
          const content = document.getElementById('ai-content');
          if (content) content.innerHTML = '<div style="color:var(--llm); margin-bottom:4px;">💬 ' + esc(m.reply) + '</div>';
        }
        if (m && m.reply) {
          const modelEl = document.getElementById('llm-model-name');
          if (modelEl) modelEl.textContent = m.reply_model ? m.reply_model.split('/').pop() : '';
        }
      }
    }

    function sendCtrl(action) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({type: 'control', action: action}));
    }

    function esc(s) {
      if (s == null) return '';
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function applyTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      const btn = document.getElementById('btn-theme');
      if (btn) btn.textContent = theme === 'light' ? '🌙' : '☀';
      localStorage.setItem('theme', theme);
    }

    function _morphIcons(fromIcon, toIcon, applyFn) {
      const overlay = document.getElementById('morph-overlay');
      if (!overlay) { applyFn(); return; }

      overlay.textContent = fromIcon;
      overlay.classList.add('active');

      setTimeout(() => {
        overlay.style.transform = 'translate(-50%, -50%) scale(120)';
        overlay.style.opacity = '1';
      }, 10);

      setTimeout(() => {
        applyFn();
        overlay.textContent = toIcon;
        overlay.style.transform = 'translate(-50%, -50%) scale(1)';
        overlay.style.opacity = '0';
        setTimeout(() => overlay.classList.remove('active'), 250);
      }, 450);
    }

    function toggleTheme() {
      const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      const next = current === 'light' ? 'dark' : 'light';
      const fromIcon = current === 'light' ? 'light_mode' : 'dark_mode';
      const toIcon = next === 'light' ? 'light_mode' : 'dark_mode';

      _morphIcons(fromIcon, toIcon, () => applyTheme(next));
    }

    function applyMode(mode) {
      const btn = document.getElementById('btn-mode');
      if (btn) btn.textContent = mode === 'dev' ? 'person' : 'code';
      document.body.classList.toggle('dev-mode', mode === 'dev');
      localStorage.setItem('dashboard-mode', mode);
      // Ensure graph is resized and re-rendered in case panels toggled
      if (_cfg) renderGraph(_cfg);
    }

    function toggleMode() {
      const current = localStorage.getItem('dashboard-mode') || 'user';
      applyMode(current === 'dev' ? 'user' : 'dev');
    }

    function toggleMonitor() {
      const sec = document.getElementById('monitoring-section');
      const collapsed = sec.classList.toggle('collapsed');
      localStorage.setItem('monitor-collapsed', collapsed ? '1' : '0');
    }

    function toggleLog() {
      const sec = document.getElementById('log-panel');
      const collapsed = sec.classList.toggle('collapsed');
      localStorage.setItem('log-collapsed', collapsed ? '1' : '0');
    }

    function showToast(message, type = 'info') {
      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.textContent = message;
      toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        padding: 12px 24px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        z-index: 2000;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        animation: slideUp 0.3s ease-out;
        max-width: 90%;
        text-align: center;
        color: #000;
      `;
      document.body.appendChild(toast);
      setTimeout(() => {
        toast.style.animation = 'slideDown 0.3s ease-in';
        setTimeout(() => toast.remove(), 300);
      }, 3000);
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

    reconnectPopupTimer = setTimeout(() => {
      const popup = document.getElementById('reconnect-popup');
      if (popup) popup.classList.remove('hidden');
      reconnectPopupTimer = null;
    }, 500);

    connect();

    // Follow OS preference changes unless user has a stored override
    matchMedia('(prefers-color-scheme: light)').addEventListener('change', function(e) {
      if (!localStorage.getItem('theme')) applyTheme(e.matches ? 'light' : 'dark');
    });
