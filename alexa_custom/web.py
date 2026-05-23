"""Web dashboard for alexa-custom — launch with: alexa-client --web"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from datetime import datetime
from typing import Any, Callable

from aiohttp import web, WSMsgType


logger = logging.getLogger(__name__)

# ── embedded single-page dashboard ────────────────────────────────────────────

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>alexa-custom</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #1a1a1a; color: #e0e0e0; font-family: 'Courier New', monospace;
           font-size: 13px; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

    #status-bar { background: #252525; padding: 7px 12px; border-bottom: 1px solid #333;
                  display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
    .sdot { width: 9px; height: 9px; border-radius: 50%; background: #555; flex-shrink: 0; }
    .sdot.ok   { background: #4caf50; }
    .sdot.warn { background: #ff9800; }
    #st { flex: 1; }
    #room { color: #666; }
    #ws-ind { font-size: 11px; color: #555; margin-left: auto; }
    #ws-ind.ok { color: #4caf50; }

    #main { display: flex; flex: 1; min-height: 0; }

    #left { width: 230px; flex-shrink: 0; border-right: 1px solid #333; display: flex; flex-direction: column; }
    #hist-section { flex: 1; min-height: 0; display: flex; flex-direction: column; }
    #hh { padding: 7px 12px; color: #7986cb; font-weight: bold; border-bottom: 1px solid #333; flex-shrink: 0; font-size: 11px; letter-spacing: .05em; }
    #hl { flex: 1; overflow-y: auto; padding: 6px 10px; }
    .he { padding: 4px 0 4px; border-bottom: 1px solid #242424; }
    .he:last-child { border-bottom: none; }
    .hts { color: #444; font-size: 11px; }
    .hwk { color: #7986cb; font-size: 11px; margin-left: 4px; }
    .hcmd { color: #e0e0e0; font-size: 12px; margin-top: 1px; }
    .htrig { color: #4caf50; font-size: 11px; margin-top: 1px; }
    #part-section { flex-shrink: 0; max-height: 38%; display: flex; flex-direction: column; border-top: 1px solid #333; }
    #ph { padding: 7px 12px; color: #7986cb; font-weight: bold; border-bottom: 1px solid #333; flex-shrink: 0; font-size: 11px; letter-spacing: .05em; }
    #pl { flex: 1; overflow-y: auto; padding: 8px 12px; }
    .pt { padding: 2px 0; }
    .pdot  { color: #4caf50; }
    .pdot0 { color: #555; }

    #log-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
    #lh { padding: 7px 12px; color: #7986cb; font-weight: bold; border-bottom: 1px solid #333;
          display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; }
    #lclr { background: none; border: 1px solid #444; color: #777; padding: 2px 7px;
            cursor: pointer; font-family: inherit; font-size: 11px; }
    #lclr:hover { border-color: #7986cb; color: #ccc; }
    #le { flex: 1; overflow-y: auto; padding: 8px 12px; }
    .le  { padding: 1px 0; white-space: pre-wrap; word-break: break-all; }
    .ts  { color: #555; }
    .DEBUG    { color: #555; }
    .INFO     { color: #4dd0e1; }
    .WARNING  { color: #ffb74d; }
    .ERROR    { color: #ef5350; }
    .CRITICAL { color: #ef5350; font-weight: bold; }

    #bot { border-bottom: 1px solid #333; padding: 9px 12px; flex-shrink: 0; }
    .vr { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; height: 15px; }
    .vl { width: 34px; color: #888; font-weight: bold; flex-shrink: 0; }
    .vd { width: 90px; color: #555; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0; }
    .vw { flex: 1; background: #2a2a2a; height: 11px; border-radius: 2px; overflow: hidden; }
    .vb { height: 100%; width: 0%; background: #4caf50; transition: width 0.06s linear; border-radius: 2px; }
    .vdb { width: 76px; text-align: right; color: #777; flex-shrink: 0; }

    #stt { margin-top: 6px; padding-top: 6px; border-top: 1px solid #333; min-height: 36px;
           display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .si  { font-size: 16px; flex-shrink: 0; }
    .swk { color: #ffb74d; font-size: 15px; font-weight: bold; }
    .smt { color: #4caf50; font-size: 15px; }
    .snm { color: #ef5350; font-size: 14px; }
    .stxt { font-size: 15px; }

    #ctl { margin-top: 7px; padding-top: 7px; border-top: 1px solid #333; }
    #btn-restart { background: #252525; border: 1px solid #555; color: #ccc;
                   padding: 4px 13px; cursor: pointer; font-family: inherit;
                   font-size: 12px; border-radius: 2px; }
    #btn-restart:hover    { border-color: #ef5350; color: #ef5350; }
    #btn-restart:disabled { opacity: 0.45; cursor: not-allowed; border-color: #333; color: #555; }
  </style>
</head>
<body>
  <div id="status-bar">
    <div class="sdot" id="cdot"></div>
    <span id="st">Connecting…</span>
    <span id="room"></span>
    <span id="ws-ind">WS disconnected</span>
  </div>
  <div id="bot">
    <div class="vr">
      <span class="vl">MIC</span><span class="vd" id="mic-dev"></span>
      <div class="vw"><div class="vb" id="mic-bar"></div></div>
      <span class="vdb" id="mic-db">-∞ dB</span>
    </div>
    <div class="vr">
      <span class="vl">SPK</span><span class="vd" id="spk-dev"></span>
      <div class="vw"><div class="vb" id="spk-bar"></div></div>
      <span class="vdb" id="spk-db">-∞ dB</span>
    </div>
    <div id="stt"><span class="si">○</span><span style="color:#555">STT inactive</span></div>
    <div id="ctl"><button id="btn-restart" onclick="sendCtrl('restart')">Restart</button></div>
  </div>
  <div id="main">
    <div id="left">
      <div id="hist-section">
        <div id="hh">HISTORY</div>
        <div id="hl"></div>
      </div>
      <div id="part-section">
        <div id="ph">PARTICIPANTS (0)</div>
        <div id="pl"><span style="color:#555">Waiting…</span></div>
      </div>
    </div>
    <div id="log-panel">
      <div id="lh"><span>LOGS</span><button id="lclr" onclick="clearLogs()">clear</button></div>
      <div id="le"></div>
    </div>
  </div>

  <script>
    let ws = null, reconnTimer = null, _restarting = false, _reconnDelay = 1000, _lastWakeWord = '';
    const parts = {};

    function connect() {
      if (ws) { try { ws.close(); } catch(e) {} }
      ws = new WebSocket('ws://' + location.host + '/ws');
      ws.onopen = () => {
        _reconnDelay = 1000;
        wsInd(true);
        if (_restarting) setSt('Reconnected — waiting…', null);
      };
      ws.onclose = () => {
        wsInd(false); ws = null;
        if (_restarting) setSt('Waiting for server…', null);
        reconnTimer = setTimeout(connect, _reconnDelay);
        _reconnDelay = Math.min(_reconnDelay * 2, 8000);
      };
      ws.onerror = () => {
        ws = null; clearTimeout(reconnTimer);
        reconnTimer = setTimeout(connect, _reconnDelay);
        _reconnDelay = Math.min(_reconnDelay * 2, 8000);
      };
      ws.onmessage = (e) => { try { handle(JSON.parse(e.data)); } catch(_) {} };
    }

    function wsInd(up) {
      const el = document.getElementById('ws-ind');
      el.textContent = up ? 'WS connected' : 'WS reconnecting…';
      el.className   = up ? 'ok' : '';
    }

    function handle(m) {
      switch (m.type) {
        case 'hello': {
          _restarting = false;
          const rb = document.getElementById('btn-restart');
          rb.disabled = false; rb.textContent = 'Restart';
          setSt(m.status, m.room);
          (m.participants || []).forEach(p => parts[p.identity] = p.tracks);
          renderParts();
          setAudio(m.audio_connected, m.audio_conn_type);
          setStt(m.stt_state, m.stt_text, m);
          break;
        }
        case 'connected':          setSt('Connected', m.room); break;
        case 'disconnected':       setSt('Disconnected — reconnecting…', null); break;
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
        case 'volume_update': setVU('mic', m.mic||0); setVU('spk', m.spk||0); break;
        case 'audio_status':  setAudio(m.connected, m.conn_type); break;
        case 'stt':
          if (m.state === 'wake' && m.word && m.word !== '(reply)') {
            _lastWakeWord = m.word;
            addHistoryWake(m.word);
          }
          if (m.state === 'matched') addHistory(_lastWakeWord, m.transcript||'', m.trigger||'');
          setStt(m.state, m.text||m.word||m.transcript||'', m);
          break;
        case 'log':           addLog(m); break;
        case 'restarting': {
          _restarting = true;
          const b = document.getElementById('btn-restart');
          b.disabled = true; b.textContent = 'Restarting…';
          setSt('Restarting…', null);
          break;
        }
        case 'error': setSt('Error: ' + (m.msg||'unknown'), null); break;
      }
    }

    function setSt(text, room) {
      document.getElementById('st').textContent = text;
      const d = document.getElementById('cdot');
      d.className = text.includes('Connected') && !text.includes('Dis') ? 'sdot ok'
                  : (text.includes('Reconnect') || text.includes('Disconnect')) ? 'sdot warn'
                  : 'sdot';
      if (room !== null)
        document.getElementById('room').textContent = room ? '│ ' + room : '';
    }

    function renderParts() {
      const keys = Object.keys(parts);
      document.getElementById('ph').textContent = 'PARTICIPANTS (' + keys.length + ')';
      const pl = document.getElementById('pl');
      if (!keys.length) { pl.innerHTML = '<span style="color:#555">Waiting…</span>'; return; }
      pl.innerHTML = keys.map(id => {
        const t = parts[id]||0;
        return '<div class="pt"><span class="' + (t?'pdot':'pdot0') + '">' + (t?'●':'○') + '</span> '
          + esc(id) + (t ? ' <span style="color:#555">'+t+'t</span>' : '') + '</div>';
      }).join('');
    }

    function setVU(ch, lvl) {
      const pct = Math.round(Math.sqrt(Math.max(0, Math.min(1, lvl))) * 100);
      const dv  = lvl > 1e-9 ? (20 * Math.log10(Math.max(lvl, 1e-9))).toFixed(1) : null;
      const bar = document.getElementById(ch+'-bar');
      const dbl = document.getElementById(ch+'-db');
      bar.style.width      = pct + '%';
      bar.style.background = dv && parseFloat(dv) > -6  ? '#ef5350'
                           : dv && parseFloat(dv) > -18 ? '#ffb74d' : '#4caf50';
      dbl.textContent = dv ? dv + ' dB' : '-∞ dB';
    }

    function setAudio(connected, connType) {
      const lbl = connected ? '[' + (connType||'').toUpperCase() + ']' : '[offline]';
      document.getElementById('mic-dev').textContent = lbl;
      document.getElementById('spk-dev').textContent = lbl;
    }

    function setStt(state, text, m) {
      const el = document.getElementById('stt');
      switch (state) {
        case 'listening':
          el.innerHTML = '<span class=”si” style=”color:#555”>○</span>'
            + '<span style=”color:#555”>wake: <em>' + esc(text) + '</em></span>'; break;
        case 'transcribing':
          el.innerHTML = '<span class=”si” style=”color:#aaa”>◌</span>'
            + '<span class=”stxt” style=”color:#bbb”>' + esc(text) + ' …</span>'; break;
        case 'wake':
          el.innerHTML = '<span class=”si swk”>◉</span>'
            + '<span class=”swk”>”' + esc(text) + '”</span>'
            + '<span style=”color:#777;font-size:13px”> listening…</span>'; break;
        case 'partial':
          el.innerHTML = '<span class=”si swk”>◉</span>'
            + '<span class=”swk”>' + esc(text) + ' …</span>'; break;
        case 'matched':
          el.innerHTML = '<span class=”si smt”>✓</span>'
            + '<span class=”smt”>”' + esc(m.transcript||text) + '”</span>'
            + '<span style=”color:#555;font-size:13px”> → </span>'
            + '<strong style=”color:#81c784;font-size:15px”>' + esc(m.trigger||'') + '</strong>'; break;
        case 'nomatch':
          el.innerHTML = '<span class=”si snm”>✗</span>'
            + '<span class=”snm”>' + (text ? '”' + esc(text) + '” ' : '') + 'no match</span>'; break;
        case 'gated':
          el.innerHTML = '<span class=”si” style=”color:#555”>⏸</span>'
            + '<span style=”color:#555”>STT paused during call</span>'; break;
        default:
          el.innerHTML = '<span class=”si” style=”color:#555”>○</span>'
            + '<span style=”color:#555”>STT inactive</span>';
      }
    }

    const MAX_LOG = 300;
    function addLog(m) {
      const el = document.getElementById('le');
      const d  = document.createElement('div');
      d.className = 'le';
      d.innerHTML = '<span class="ts">' + esc(m.ts) + ' </span>'
                  + '<span class="' + m.level + '">' + m.level.padEnd(8) + '</span> '
                  + esc(m.msg);
      el.appendChild(d);
      while (el.children.length > MAX_LOG) el.removeChild(el.firstChild);
      el.scrollTop = el.scrollHeight;
    }

    function clearLogs() { document.getElementById('le').innerHTML = ''; }

    const MAX_HIST = 60;
    function addHistoryWake(word) {
      const el = document.getElementById('hl');
      if (!el) return;
      const ts = new Date().toTimeString().slice(0, 8);
      const d = document.createElement('div');
      d.className = 'he';
      d.innerHTML = '<span class="hts">' + ts + '</span>'
        + ' <span style="color:#ffb74d">◉ ' + esc(word) + '</span>';
      el.insertBefore(d, el.firstChild);
      while (el.children.length > MAX_HIST) el.removeChild(el.lastChild);
    }

    function addHistory(wake, transcript, trigger) {
      const el = document.getElementById('hl');
      if (!el) return;
      const ts = new Date().toTimeString().slice(0, 8);
      const d = document.createElement('div');
      d.className = 'he';
      d.innerHTML = '<div><span class="hts">' + ts + '</span>'
        + (wake ? '<span class="hwk">' + esc(wake) + '</span>' : '') + '</div>'
        + '<div class="hcmd">“' + esc(transcript) + '”</div>'
        + (trigger && trigger !== transcript
            ? '<div class="htrig">→ ' + esc(trigger) + '</div>' : '');
      el.insertBefore(d, el.firstChild);
      while (el.children.length > MAX_HIST) el.removeChild(el.lastChild);
    }

    function sendCtrl(action) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({type: 'control', action}));
    }

    function esc(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    connect();
  </script>
</body>
</html>
"""

# ── log handler ────────────────────────────────────────────────────────────────


class _WebLogHandler(logging.Handler):
    def __init__(self, server: WebServer) -> None:
        super().__init__()
        self._server = server

    def emit(self, record: logging.LogRecord) -> None:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        self._server._enqueue(
            "log",
            {
                "level": record.levelname,
                "ts": ts,
                "msg": record.getMessage(),
            },
        )


# ── web server ─────────────────────────────────────────────────────────────────


class WebServer:
    def __init__(self, port: int = 8080) -> None:
        self._port = port
        self._clients: set[web.WebSocketResponse] = set()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._pending_vu: dict[str, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._livekit_loop: asyncio.AbstractEventLoop | None = None
        self._livekit_stop_event: asyncio.Event | None = None
        self._handler: _WebLogHandler | None = None
        # snapshot for hello message on new WS connects
        self._state: dict[str, Any] = {
            "status": "Starting…",
            "room": "",
            "participants": {},
            "audio_connected": False,
            "audio_conn_type": "",
            "stt_state": "idle",
            "stt_text": "",
        }

    # ── thread-safe enqueue ───────────────────────────────────────────────────

    def _enqueue(self, event_type: str, data: dict) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(
                self._queue.put_nowait, {"type": event_type, **data}
            )
        except Exception:
            pass

    def _update_pending_vu(self, mic: float, spk: float) -> None:
        """Must run on the event loop (via call_soon_threadsafe)."""
        self._pending_vu["mic"] = mic
        self._pending_vu["spk"] = spk

    # ── callbacks (same signatures as tui.py) ────────────────────────────────

    def on_event(self, event: str, data: dict) -> None:
        if event == "connected":
            self._state["status"] = "Connected"
            self._state["room"] = data.get("room", "")
        elif event == "disconnected":
            self._state["status"] = "Disconnected — reconnecting…"
        elif event == "reconnecting":
            self._state["status"] = "Reconnecting…"
        elif event == "empty_room_timeout":
            self._state["status"] = "Disconnected — empty room"
        elif event == "participant_joined":
            self._state["participants"][data["identity"]] = 0
        elif event == "participant_left":
            self._state["participants"].pop(data["identity"], None)
        elif event == "track_subscribed":
            identity = data["identity"]
            self._state["participants"][identity] = (
                self._state["participants"].get(identity, 0) + 1
            )
        elif event == "track_unsubscribed":
            identity = data["identity"]
            if identity in self._state["participants"]:
                self._state["participants"][identity] = max(
                    0, self._state["participants"][identity] - 1
                )
        elif event == "volume_update":
            loop = self._loop
            if loop and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(
                        self._update_pending_vu,
                        data.get("mic", 0.0),
                        data.get("spk", 0.0),
                    )
                except Exception:
                    pass
            return
        self._enqueue(event, data)

    def on_stt_event(self, event: str, data: dict) -> None:
        if event == "level":
            loop = self._loop
            if loop and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(
                        self._update_pending_vu,
                        data.get("mic", 0.0),
                        self._pending_vu.get("spk", 0.0),
                    )
                except Exception:
                    pass
            return

        if event == "listening":
            self._state["stt_state"] = "listening"
            self._state["stt_text"] = ", ".join(data.get("wake_words", []))
        elif event in (
            "transcribing",
            "wake",
            "partial",
            "matched",
            "nomatch",
            "gated",
        ):
            self._state["stt_state"] = event
            self._state["stt_text"] = data.get(
                "text", data.get("word", data.get("transcript", ""))
            )

        self._enqueue("stt", {"state": event, **data})

    def on_audio_status(self, connected: bool, conn_type: str) -> None:
        self._state["audio_connected"] = connected
        self._state["audio_conn_type"] = conn_type
        self._enqueue("audio_status", {"connected": connected, "conn_type": conn_type})

    # ── HTTP / WebSocket routes ───────────────────────────────────────────────

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=_HTML, content_type="text/html")

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)

        participants_list = [
            {"identity": k, "tracks": v} for k, v in self._state["participants"].items()
        ]
        await ws.send_str(
            json.dumps(
                {
                    "type": "hello",
                    "status": self._state["status"],
                    "room": self._state["room"],
                    "participants": participants_list,
                    "audio_connected": self._state["audio_connected"],
                    "audio_conn_type": self._state["audio_conn_type"],
                    "stt_state": self._state["stt_state"],
                    "stt_text": self._state["stt_text"],
                }
            )
        )

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") == "control":
                        await self._handle_control(payload.get("action", ""))
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            self._clients.discard(ws)

        return ws

    async def _handle_control(self, action: str) -> None:
        if action == "restart":
            logger.info("Restart requested via web dashboard")
            await self._broadcast({"type": "restarting"})
            await asyncio.sleep(0.15)
            os.execv(sys.executable, sys.argv)

    # ── broadcast helpers ─────────────────────────────────────────────────────

    async def _broadcast(self, msg: dict) -> None:
        if not self._clients:
            return
        text = json.dumps(msg)
        dead: set[web.WebSocketResponse] = set()
        for ws in list(self._clients):
            try:
                await ws.send_str(text)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def _broadcast_loop(self) -> None:
        while True:
            msg = await self._queue.get()
            await self._broadcast(msg)

    async def _vu_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            if self._pending_vu:
                await self._broadcast({"type": "volume_update", **self._pending_vu})
                self._pending_vu.clear()

    async def _prune_clients_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            self._clients = {ws for ws in self._clients if not ws.closed}

    # ── logging ───────────────────────────────────────────────────────────────

    def _install_log_handler(self) -> None:
        root = logging.getLogger()
        self._handler = _WebLogHandler(self)
        self._handler.setLevel(logging.DEBUG)
        root.addHandler(self._handler)

    def _uninstall_log_handler(self) -> None:
        if self._handler:
            logging.getLogger().removeHandler(self._handler)

    # ── LiveKit worker thread ─────────────────────────────────────────────────

    def _livekit_worker(
        self,
        run_fn: Callable,
        stop_threading: threading.Event,
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._livekit_loop = loop
        livekit_stop = asyncio.Event()
        self._livekit_stop_event = livekit_stop

        def _exc_handler(lp: asyncio.AbstractEventLoop, context: dict) -> None:
            if isinstance(context.get("exception"), asyncio.QueueFull):
                return
            lp.default_exception_handler(context)

        loop.set_exception_handler(_exc_handler)
        try:
            loop.run_until_complete(run_fn(stop_threading, self.on_event, livekit_stop))
        except Exception as e:
            self._enqueue("error", {"msg": str(e)})
        finally:
            loop.close()

    # ── main coroutine ────────────────────────────────────────────────────────

    async def run(
        self,
        run_fn: Callable,
        input_spec: str | None,
        output_spec: str | None,
        room: str,
        stt_params: dict | None = None,
    ) -> None:
        self._loop = asyncio.get_running_loop()
        self._install_log_handler()

        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/ws", self._handle_ws)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self._port)
        await site.start()
        logger.info("Web dashboard available at http://0.0.0.0:%d", self._port)

        broadcast_task = asyncio.create_task(self._broadcast_loop())
        vu_task = asyncio.create_task(self._vu_flush_loop())
        prune_task = asyncio.create_task(self._prune_clients_loop())

        stop_threading = threading.Event()
        livekit_thread = threading.Thread(
            target=self._livekit_worker,
            args=(run_fn, stop_threading),
            daemon=True,
            name="livekit-web",
        )
        livekit_thread.start()

        from alexa_custom.audio import AudioWatcher

        audio_watcher = AudioWatcher(
            input_spec=input_spec,
            output_spec=output_spec,
            on_status_change=self.on_audio_status,
        )
        audio_watcher.start()

        if stt_params is not None:
            from alexa_custom.stt import start_stt_thread

            start_stt_thread(
                config=stt_params["config"],
                stop_event=stt_params["stop_event"],
                telegram_client=stt_params["telegram_client"],
                livekit_connect_fn=stt_params["connect_fn"],
                livekit_connected_flag=stt_params["connected_flag"],
                on_stt_event=self.on_stt_event,
            )

        try:
            await asyncio.Future()  # blocks until cancelled (Ctrl+C)
        except asyncio.CancelledError:
            pass
        finally:
            lk_loop = self._livekit_loop
            lk_stop = self._livekit_stop_event
            if lk_loop and lk_stop and not lk_loop.is_closed():
                lk_loop.call_soon_threadsafe(lk_stop.set)
            stop_threading.set()
            if stt_params:
                stt_params["stop_event"].set()
            audio_watcher.stop()
            for ws in list(self._clients):
                try:
                    await ws.close()
                except Exception:
                    pass
            broadcast_task.cancel()
            vu_task.cancel()
            prune_task.cancel()
            await runner.cleanup()
            self._uninstall_log_handler()


# ── public entry point ─────────────────────────────────────────────────────────


def run_web(
    run_fn: Callable,
    input_spec: str | None,
    output_spec: str | None,
    room: str,
    stt_params: dict | None = None,
    port: int = 8080,
) -> None:
    server = WebServer(port=port)
    try:
        asyncio.run(server.run(run_fn, input_spec, output_spec, room, stt_params))
    except KeyboardInterrupt:
        pass
