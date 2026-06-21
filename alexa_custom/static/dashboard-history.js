    // ── History & Logging ──────────────────────────────────────────────────

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
          hl.style.display = '';
          empty.style.display = 'none';
        } else {
          hl.style.display = 'none';
          empty.style.display = 'block';
        }
      }
    }

    function _clearHistoryDOM() {
      document.getElementById('hl').innerHTML = '';
      updateHistoryVisibility();
    }

    function clearHistory() {
      _clearHistoryDOM();
      sendCtrl('clear_history');
    }

    function flagFalsePositive(session_id, btn) {
      sendCtrl('flag_fp:' + session_id);
      // Immediate visual feedback — don't wait for a page reload / server echo.
      const item = btn ? btn.closest('.he') : document.querySelector('.he[data-id="' + session_id + '"]');
      if (item) {
        item.classList.add('fp-flagged');
        const row = item.querySelector('.he-action-row');
        if (row) {
          row.innerHTML = '<span class="hflagged" style="font-size:9px;color:var(--nomatch);font-weight:bold;margin-left:auto;">⚠️ Flagged</span>';
        }
      }
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
        actionBtnHtml = '<button class="hflag-btn" onclick="flagFalsePositive(\'' + esc(session_id) + '\', this)" style="margin-left:auto;font-size:9px;background:rgba(255,255,255,0.06);border:1px solid var(--border);border-radius:4px;color:var(--muted);padding:1px 5px;cursor:pointer;">Flag FP</button>';
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
