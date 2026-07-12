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
        const word = typeof ww === 'string' ? ww : (ww.word || '');
        html += `
          <div style="display: flex; align-items: center; gap: 8px; background: var(--surface); padding: 8px; border-radius: 6px; border: 1px solid var(--border);">
            <span style="color: var(--info); font-weight: 500;">${word}</span>
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
            <label>Wake Window (seconds)</label>
            <input type="number" id="input-wake-window" step="0.5" min="1">
            <span class="form-hint">How long to listen for a command after a wake word</span>
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

      document.getElementById('input-wake-window').value = config.recognition?.wake_window ?? '';
      document.getElementById('input-matching-threshold').value = config.recognition?.matching_threshold ?? '';
      document.getElementById('input-matching-algorithm').value = config.recognition?.matching_algorithm || 'token_set_ratio';
      document.getElementById('input-reply-matching-algorithm').value = config.recognition?.reply_matching_algorithm || 'levenshtein';
      document.getElementById('input-reply-matching-threshold').value = config.recognition?.reply_matching_threshold ?? '';
      document.getElementById('input-follow-up').value = config.recognition?.follow_up ? 'true' : 'false';
      document.getElementById('input-follow-up-timeout').value = config.recognition?.follow_up_timeout ?? '';
      document.getElementById('input-follow-up-max-turns').value = config.recognition?.follow_up_max_turns ?? '';
      document.getElementById('input-stt-backend').value = config.stt?.backend || 'vosk';
      document.getElementById('input-rms-threshold').value = config.stt?.rms_threshold ?? '';
      document.getElementById('input-adaptive-rms').value = config.stt?.adaptive_rms !== false ? 'true' : 'false';
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

      currentConfig.wake_words.push(word);

      input.value = '';
      renderConfigForm(currentConfig);
    }

    function collectFormData() {
      const wws = (currentConfig.wake_words || []).map(w => typeof w === 'string' ? w : (w.word || w));
      const result = { wake_words: wws };

      const wakeWindow = parseFloat(document.getElementById('input-wake-window').value);
      result.recognition = {
        matching_algorithm: document.getElementById('input-matching-algorithm').value,
        reply_matching_algorithm: document.getElementById('input-reply-matching-algorithm').value,
        follow_up: document.getElementById('input-follow-up').value === 'true',
      };
      // Only include numeric fields if they parse — NaN serializes to JSON null
      // which breaks the daemon's float() coercion on cold start.
      if (!isNaN(wakeWindow)) result.recognition.wake_window = wakeWindow;
      const matchingThreshold = parseFloat(document.getElementById('input-matching-threshold').value);
      if (!isNaN(matchingThreshold)) result.recognition.matching_threshold = matchingThreshold;
      const replyThreshold = parseFloat(document.getElementById('input-reply-matching-threshold').value);
      if (!isNaN(replyThreshold)) result.recognition.reply_matching_threshold = replyThreshold;
      const followUpTimeout = parseFloat(document.getElementById('input-follow-up-timeout').value);
      if (!isNaN(followUpTimeout)) result.recognition.follow_up_timeout = followUpTimeout;
      const followUpMaxTurns = parseInt(document.getElementById('input-follow-up-max-turns').value, 10);
      if (!isNaN(followUpMaxTurns)) result.recognition.follow_up_max_turns = followUpMaxTurns;

      result.stt = {
        backend: document.getElementById('input-stt-backend').value,
        adaptive_rms: document.getElementById('input-adaptive-rms').value === 'true',
      };
      const rmsThreshold = parseFloat(document.getElementById('input-rms-threshold').value);
      if (!isNaN(rmsThreshold)) result.stt.rms_threshold = rmsThreshold;

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