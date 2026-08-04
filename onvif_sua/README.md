# ONVIF Events Monitor

Container Docker per il monitoraggio di telecamere IP ONVIF su rete locale.  
Progetto sviluppato per la gestione di telecamere Dahua con rilevamento caduta (fall detection), pubblicazione MQTT verso Home Assistant e interfaccia web di controllo.

---

## Funzionalità principali

- **Configurazione delle telecamere in `settings.yaml`** (blocco `cameras`) — ogni telecamera è dichiarata con un `name` e **uno fra** `ip:` (indirizzo fisso) e `hostname:` (hostname ONVIF del device), in un unico file YAML. Il servizio avvia esattamente un worker per ogni voce elencata; nessuna telecamera viene aggiunta da sé, a meno che non si abiliti il rescan automatico.
- **Indirizzamento per hostname ONVIF (per subnet in DHCP)** — una voce `hostname:` viene risolta all'IP corrente scansionando la subnet e confrontando l'hostname riportato da ogni device: all'avvio, ogni 10 minuti e ad ogni scan. Se l'IP cambia, il worker viene spostato sul nuovo indirizzo conservando il `name`; se due device riportano lo stesso hostname la telecamera resta **non risolta** invece di agganciare quella sbagliata. L'IP risolto vive solo in memoria: `settings.yaml` non viene mai riscritto con un indirizzo.
- **Rescan automatico opzionale** — `scan.rescan_time_interval` (0 = disabilitato, il default) ripete lo scan della subnet a intervalli, misurati dall'ultimo scan. Un rescan automatico non re-aggiunge una telecamera rimossa dall'operatore. La scansione resta comunque disponibile come strumento **manuale** dalla GUI.
- **Credenziale comune unica** — un solo `user`/`pass` (dal file `.env`) + `port` (in `settings.yaml`) applicato a tutte le telecamere (nessuna lista di fallback), per eliminare il rischio di blocco anti-intrusione Dahua.
- **Protezione anti-lockout su login fallito** — al **primo** errore di autenticazione (HTTP 401/403 su una qualsiasi via CGI, o rifiuto credenziali ONVIF) la telecamera viene messa **in quarantena**: tutti i loop di retry per quell'IP (worker ONVIF, attach CGI, keepalive, rule-check, scan) si **fermano**, così una password sbagliata-ma-reale non può martellare la telecamera fino al blocco anti-intrusione Dahua. Un avviso è mostrato nel log e nella dashboard ("cambia la password in `.env` e riavvia"). Gli errori transitori/di rete mantengono invece il normale backoff (un disturbo momentaneo non disabilita mai la telecamera).
- **Liveness del rilevamento (`detection_ok`)** — prova continua che la pipeline di fall detection di ogni telecamera è *attiva*, non solo che la telecamera è accesa: heartbeat sullo stream eventi + watchdog di gap + verifica periodica che la regola analytics sia abilitata.
- **ONVIF PullPoint subscription** — riceve eventi in tempo reale (motion, AI, I/O, audio, ecc.); indipendente dalla liveness (un errore ONVIF non ferma il rilevamento)
- **Fall detection Dahua via CGI** — la telecamera Dahua IPC-HDW8441X-BV-3D non espone il fall detection tramite ONVIF; l'evento `TumbleDetection` viene catturato tramite stream HTTP CGI (`/cgi-bin/eventManager.cgi?action=attach&codes=[All]`)
- **Debounce allarme caduta** — primo evento `Start` → allarme ON; il timer si azzera ad ogni nuovo `Start`; dopo 10 secondi dall'ultimo `Stop` senza nuovi `Start` → allarme OFF
- **File `alarm.json`** — stato allarmi scritto atomicamente su `/data/alarm.json`, leggibile via HTTP
- **MQTT con Home Assistant Discovery** — pubblica topic per ogni allarme con auto-discovery HA (binary_sensor, device_class: safety, icona: mdi:account-injury)
- **Web UI con login** — dashboard, log eventi, filtri per categoria, stato allarmi in tempo reale, avvisi per password da configurare e per telecamere in quarantena (login fallito)
- **Pagina impostazioni** — configurazione subnet (scan manuale) e broker MQTT, persistenti in `settings.yaml`. Le password (telecamere / scan / login GUI) stanno nel file `.env`, non nella GUI
- **Rinomina telecamera via ONVIF** — `SetHostname` direttamente dalla dashboard (icona matita). Per una telecamera configurata per `hostname:` la rinomina riscrive anche quel campo in `settings.yaml`, perché è lo stesso valore su cui si basa la risoluzione

---

## Architettura

```
Docker container (network_mode: host)
├── FastAPI + uvicorn  →  Web UI :8081
├── settings.yaml      (file config: MQTT, subnet scan, intervallo rescan,
│                       + lista telecamere `cameras` (ip: o hostname:) — RW)
├── .env                (password: telecamere / scan / login GUI — git-ignored)
├── asyncio loop
│   ├── Camera worker (una per voce di settings.yaml `cameras.list`)
│   │   ├── ONVIF PullPoint subscription (best-effort, con backoff)
│   │   ├── Dahua CGI attach stream thread (eventi + heartbeat liveness)
│   │   └── Rule-check task (regola fall detection abilitata?)
│   ├── hostname-resolve loop  (subito all'avvio, poi ogni 600s)
│   │                          risolve le voci `hostname:` all'IP corrente e
│   │                          sposta il worker quando l'indirizzo cambia
│   ├── auto-rescan loop       (dormiente se `scan.rescan_time_interval` = 0)
│   ├── detect-republish loop  (detection_ok su MQTT)
│   ├── mqtt-alarm-keepalive loop
│   ├── serena-fault-driver loop  (annunci "sensore non attivo", opt-in)
│   ├── (scan manuale one-shot, su richiesta operatore)
│   └── MQTT client (paho-mqtt)
└── /data/
    ├── alarm.json      (stato allarmi corrente)
    └── events.json     (log eventi)
```

Il codice è il pacchetto `onvif_sua/` (ex `app.py` monolitico; refactor
**behavior-preserving**), con import a senso unico `config, state → connect, mqtt →
scan, worker → web`:

```
onvif_sua/
├── __main__.py   entrypoint main() (console `onvif-sua` e `python -m onvif_sua`)
├── config.py     env, settings.yaml load/save, _cfg, credenziali, asset_version
├── state.py      stato runtime condiviso (_lock, registry camere, allarmi, backoff)
├── connect.py    ONVIF connect/services/close (NON `onvif`: non deve shadoware la libreria)
├── mqtt.py       discovery + publish (device / detect / detection_ok / keepalive)
├── scan.py       scan subnet (_probe_ip / _subnet_scan_once) + risoluzione
│                 hostname→IP (_match_hostnames / _resolve_hostnames)
├── worker.py     camera worker, thread Dahua CGI/keepalive, rule-check,
│                 loop periodici (hostname-resolve, auto-rescan, …), loop principale
└── web/          FastAPI: app.py (app+auth), routes.py (/api/*), templates/, static/
```

Fuori dal pacchetto:

```
tools/
└── onvif_hostname_probe.py   diagnostica: cosa riporta davvero una telecamera per
                              GetHostname() (vedi "Telecamere per hostname")
tests/                        pytest (nessun hardware necessario)
openspec/                     specifiche del comportamento (specs/) e storico (changes/)
```

---

## Telecamere supportate e testate

| IP              | Modello                     | Note                                      |
|-----------------|-----------------------------|-------------------------------------------|
| 192.168.110.217 | Dahua IPC-HDW8441X-BV-3D    | Fall detection via CGI, nome ONVIF configurato |
| 192.168.110.203 | Dahua IPC (generico)        | Motion detection via CGI                  |

Le telecamere si configurano nel blocco `cameras` di `settings.yaml` (vedi sotto).
La subnet dello scan è usata solo dallo scan manuale della GUI.

---

## Porte

| Porta | Protocollo | Servizio                        |
|-------|------------|---------------------------------|
| 8081  | HTTP       | Web UI e REST API               |
| 1883  | TCP/MQTT   | Broker Mosquitto (esterno)      |
| 80    | TCP        | Probe ONVIF telecamere          |

---

## Accesso web

| URL                        | Accesso    | Descrizione                            |
|----------------------------|------------|----------------------------------------|
| `http://<host>:8081/`      | 🔒 login   | Dashboard principale                   |
| `http://<host>:8081/settings` | 🔒 login | Pagina impostazioni                    |
| `http://<host>:8081/login` | pubblico   | Pagina di login                        |
| `http://<host>:8081/logout`| pubblico   | Logout (cancella cookie sessione)      |
| `http://<host>:8081/alarm.json` | pubblico | Stato allarmi (per HA/esterni)    |
| `http://<host>:8081/api/alarms` | pubblico | Allarmi JSON (per HA/esterni)    |

### Credenziale web

La password di accesso alla GUI si imposta nella variabile **`GUI_PASSWORD`** del
file `.env` (vedi `.env.example`). Viene hashata in memoria all'avvio con
PBKDF2-SHA256 (260.000 iterazioni + salt casuale) e non è mai restituita in chiaro
da nessuna API né scritta in `settings.yaml`.

Per cambiarla: modifica `GUI_PASSWORD` in `.env` e riavvia il servizio (non esiste
più il cambio password dalla GUI).

La sessione è gestita tramite cookie `HttpOnly` firmato con HMAC-SHA256 su segreto ephemero (rigenerato ad ogni riavvio del container).

---

## Configurazione statica delle telecamere (blocco `cameras` di `settings.yaml`)

Le telecamere **non** vengono più scoperte con la scansione della subnet: sono
dichiarate nel blocco `cameras` di `settings.yaml`, un file **identico in ogni kit**.
All'avvio il servizio crea esattamente un worker per ogni voce; l'identità
MQTT/Home Assistant di ogni telecamera deriva dal `name` configurato qui (mai
dall'hostname ONVIF).

### Schema

```yaml
# settings.yaml — blocco cameras (identico in ogni kit)
cameras:
  credentials:
    port: 80             # comune a tutte le telecamere (user/pass stanno in .env)
  list:
    - ip: 192.168.110.248
      name: SOGGIORNO
    - ip: 192.168.110.110
      name: BAGNO
    - hostname: STANZA_11   # alternativa a `ip` — vedi "Telecamere per hostname"
      name: CUCINA
```

Ogni voce richiede `name` ed **esattamente una** fra `ip` (indirizzo statico) e
`hostname` (hostname ONVIF del device, risolto a runtime). Una voce che ne indica
**entrambi** o **nessuno** viene ignorata con una diagnostica nel log.

`user`/`pass` della credenziale comune si impostano in `.env`
(**`CAMERA_USER`** / **`CAMERA_PASSWORD`**), non qui: in `settings.yaml` resta solo
la `port`. Vedi `.env.example`.

- **Credenziale comune unica**: `user`/`pass` (da `.env`) e `port` sono letti una
  volta e applicati a *tutte* le telecamere. Nessuna lista di fallback, nessun probing di porte multiple
  per i worker persistenti — i tentativi ripetuti con password errata attivano il blocco
  anti-intrusione Dahua.
- **Quarantena su login fallito**: al primo errore di autenticazione (HTTP 401/403 CGI
  o rifiuto credenziali ONVIF) la telecamera viene messa in quarantena e **ogni retry per
  quell'IP si ferma** — non c'è più backoff-e-riprova all'infinito (che avrebbe finito per
  bloccare la telecamera). Il sensore `fall_sensor_online` va **offline** in HA e la
  dashboard mostra l'avviso. La quarantena è in memoria: si esce correggendo la password in
  `.env` e **riavviando** (oppure rimuovendo/ri-aggiungendo la telecamera dopo il fix). Gli
  errori di rete/timeout **non** mettono in quarantena: mantengono il normale backoff.
- **Validazione**: ogni voce deve avere `name` **unico** e un `ip` (o `hostname`) **unico**.
  Un `ip`, `hostname` o `name` duplicato è un errore di configurazione: viene loggato e le voci
  in collisione **non** vengono avviate (nessuna deduplica silenziosa, nessuna sovrascrittura
  di entità MQTT). Il confronto fra hostname è case-insensitive (`STANZA_11` == `stanza_11`).
- **Nomi ripetibili tra kit**: poiché ogni appartamento ha il proprio HA/broker isolato, gli
  stessi nomi (SOGGIORNO/BAGNO) si ripetono in tutti i ~200 kit senza collisioni.
- **Preservato dalla GUI**: un salvataggio delle impostazioni dalla web UI riscrive
  `settings.yaml` mantenendo intatto il blocco `cameras` (le telecamere si editano a mano).
- **Casi limite** (blocco mancante / malformato / lista vuota): il servizio logga un errore
  chiaro e **non** avvia alcun worker, **senza** ricadere in una scansione della subnet. La web
  UI e lo scan manuale restano comunque disponibili.

Lo schema completo è mostrato più sotto (sezione **File di stato → `settings.yaml`**);
l'intestazione commentata del `settings.yaml` committato riporta il blocco `cameras` di esempio.

### Telecamere per hostname (senza IP fisso)

Quando le telecamere prendono l'indirizzo in DHCP, l'unico identificatore stabile è
l'**hostname ONVIF** del device. Una voce può quindi dichiarare `hostname:` al posto
di `ip:`; il servizio ne ricava l'IP corrente da solo.

```yaml
cameras:
  list:
    - hostname: STANZA_11    # identità di *discovery*
      name: cucina           # identità MQTT / Home Assistant / Serena
```

- **`hostname` deve essere l'hostname ONVIF del device** — il valore restituito da
  `GetHostname()`, quello che la dashboard mostra come nome rilevato dopo un rescan.
  **Non** è un nome DNS/DHCP: la risoluzione non usa DNS né mDNS.

> ⚠️ **L'hostname della pagina web della telecamera NON è (necessariamente) l'hostname
> ONVIF.** Verificato su **Dahua DH-IPC-HDW8441X-BV-3D**, firmware
> `3.140.0000000.40.R (2025-03-25)`: con l'hostname impostato a `cucina` dalla pagina
> web, ONVIF continua a riportare `GetHostname().Name = 'IPC'` (`FromDHCP=False`) —
> sono due impostazioni distinte, e quella della pagina web (hostname del client DHCP)
> non è esposta via ONVIF. Una voce `hostname: cucina` **non si risolverebbe mai**.
>
> Peggio: `IPC` è il valore **di fabbrica**, quindi è identico su tutte le telecamere di
> questo modello. Con due o più telecamere in subnet, `hostname: IPC` finisce nel caso
> **ambiguo** e non viene risolto affatto (per progetto: non si indovina quale delle due
> è la cucina). Prima di usare la configurazione per hostname, ogni telecamera deve avere
> un hostname ONVIF **distinto**, assegnato con la **rinomina dalla dashboard** (che
> scrive via `SetHostname`, l'unico campo che conta) — non dalla pagina web del device.
>
> Su questa firmware la scrittura **funziona**: verificato che dopo una rinomina
> `GetHostname()` riporta il nuovo valore (`IPC` → `bagno1`), quindi la configurazione
> per hostname è utilizzabile su questo modello. Il salvataggio di una telecamera
> scoperta rifiuta comunque un hostname già usato da un'altra voce, così due telecamere
> ancora sul default `IPC` non possono produrre due voci che al riavvio verrebbero
> scartate entrambe.
>
> Per sapere cosa riporta davvero una telecamera (senza modificarla):
>
> ```bash
> uv run python tools/onvif_hostname_probe.py <IP>
> ```
>
> Lo script stampa `GetDeviceInformation`, `GetHostname`, gli scope ONVIF e la riga
> esatta da mettere in `settings.yaml`. Con `--set NOME` esegue anche la scrittura
> (la stessa che fa il pulsante di rinomina) e rilegge il valore, per verificare se la
> firmware la onora: utile prima di adottare `hostname:` su un modello nuovo. **Se
> `SetHostname` viene accettato ma ignorato, su quel modello la configurazione per
> hostname non è utilizzabile: usa voci con `ip:` statico** (o un lease DHCP fisso).
- **`name` resta l'unica identità** usata per i topic MQTT, la discovery Home Assistant,
  lo stato allarme persistito e la frase vocale Serena. `hostname` serve **solo** a
  trovare l'IP. I due valori possono coincidere o differire: entrambi i casi sono validi
  (es. `hostname: STANZA_11` + `name: soggiorno`).
- **Risoluzione**: all'avvio (subito, senza attendere) e poi **ogni 10 minuti** il
  servizio scansiona `scan.subnet`, interroga `GetHostname()` su ogni device ONVIF che
  risponde e confronta il valore con gli `hostname` configurati (trimmed,
  case-insensitive). Una sola scansione risolve tutte le telecamere, non una per camera.
- **Il worker parte quando l'hostname è risolto.** Un hostname non ancora risolto non ha
  worker (la telecamera risulta down) e viene ritentato ad ogni giro, senza riavvii.
- **Se una risoluzione fallisce si mantiene l'ultimo IP noto** e il worker resta in
  esecuzione: un blip di rete o di scan non deve far cadere una telecamera funzionante.
- **Se l'IP cambia**, il worker viene fermato sull'IP vecchio e riavviato su quello nuovo
  conservando il `name` (l'allarme viene ripubblicato dal nuovo worker). La telecamera
  resta **una sola riga** in dashboard: quella sul nuovo indirizzo.
- **Anche uno scan (manuale o automatico) riconcilia l'indirizzo**, non solo il ciclo da
  10 minuti: un device che riporta l'hostname ONVIF di una voce configurata **non** è una
  nuova scoperta, è quella telecamera a un nuovo indirizzo. Lo scan quindi sostituisce il
  worker vecchio invece di aggiungere una seconda riga, e un cambio di indirizzo viene
  recepito alla cadenza dello scan. Un device che riporta un hostname configurato non
  viene **mai** adottato come "telecamera scoperta" — nemmeno quando l'hostname è
  ambiguo (in quel caso non si tocca nulla: vedi la regola sull'ambiguità).
- **Due device che riportano lo stesso hostname = non risolto.** Il servizio **non ne
  sceglie uno**: agganciare il gemello sbagliato sorveglierebbe una stanza annunciandone
  un'altra (`name` è il nome della stanza in ogni allarme, topic MQTT, entità HA e frase
  Serena) — un errore *silenzioso*. Non risolvere è invece un errore *dichiarato*:
  nessun worker e nessuna riga in dashboard. Un worker già in esecuzione **non** viene
  mai spostato in questo caso. Si rientra assegnando hostname distinti ai device: la
  scansione successiva risolve da sola.
  > ⚠️ Se la telecamera **non si è mai risolta** (spenta al primo avvio, hostname
  > sbagliato, o ambigua da subito) il driver dei guasti Serena **non** la annuncia: itera
  > le telecamere configurate ma salta quelle senza riga runtime, e una voce `hostname:`
  > mai risolta non ne ha. È assente dalla dashboard, ma nessuno lo dice a voce. Dopo la
  > prima risoluzione la riga esiste e gli annunci di guasto funzionano normalmente.
  > Verifica quindi dopo il primo avvio che tutte le telecamere compaiano in dashboard.
- **L'IP risolto vive solo in memoria**: non viene mai riscritto in `settings.yaml`, dove
  l'`hostname` resta il valore autoritativo (anche dopo un salvataggio dalla GUI).
- La scansione di risoluzione è **indipendente** dal rescan manuale: non tocca il flag
  `scan_active` né il pulsante di stop scan.
- **Rollback**: rimetti `ip:` al posto di `hostname:` e riavvia (l'ultimo IP risolto è nel log).

#### Salvataggio di una telecamera scoperta (💾) — voce per hostname

Il pulsante 💾 su una telecamera trovata dallo scan manuale la persiste in
`cameras.list` **come voce `hostname:`**, usando l'hostname ONVIF che il device ha
riportato durante lo scan — così un futuro cambio di lease DHCP viene seguito
automaticamente, senza modificare `settings.yaml` a mano.

- Il salvataggio **non scrive nulla sul device**: registra l'hostname che la telecamera
  già riporta. Se vuoi un hostname diverso, **rinomina** la telecamera (che lo imposta
  via `SetHostname`) e poi salva.
- Se il device **non riporta alcun hostname ONVIF**, la voce ricade su `ip:` statico e la
  cosa viene loggata (un cambio di lease richiederà una modifica manuale).
- Se l'hostname riportato è **già usato da un'altra voce**, il salvataggio viene
  **rifiutato (409)** con l'indicazione di rinominare prima una delle due. È il caso
  tipico di due telecamere ancora sull'hostname di fabbrica (`IPC`): due voci con lo
  stesso hostname verrebbero scartate **entrambe** al prossimo avvio, spegnendo due
  telecamere funzionanti.
- Una voce **già esistente** conserva la sua forma: salvare una telecamera già
  configurata con `ip:` statico ne aggiorna solo il `name`, non la converte a `hostname:`
  (e viceversa). La conversione è una scelta esplicita da fare a mano nel file.
- La telecamera salvata è subito visibile al ciclo di risoluzione (nessun riavvio
  necessario) e il suo IP corrente viene messo in cache.

#### Rinomina di una telecamera configurata per hostname

Il pulsante di rinomina imposta l'**hostname ONVIF sul device** (`SetHostname`) — cioè
esattamente il valore su cui si basa la risoluzione. Di conseguenza:

- Rinominando una telecamera configurata per hostname, il servizio **riscrive anche
  `hostname:`** nella sua voce di `settings.yaml`, nello stesso salvataggio del `name`,
  così la voce continua a risolversi. Viene scritto l'hostname che il **device riporta**
  dopo la rinomina (se il firmware lo normalizza o lo tronca, la voce resta comunque
  corretta); se la rilettura di verifica fallisce viene scritto il nome richiesto e la
  cosa è loggata come warning.
- **Dopo la prima rinomina `hostname` e `name` coincidono**: l'hostname di fabbrica
  originale non è più ricostruibile dalla configurazione. Il valore precedente è nel log.
- La rinomina **non riavvia il worker** (l'IP non è cambiato, solo la chiave con cui è
  in cache).
- Una rinomina che assegnerebbe alla telecamera l'`hostname` **di un'altra voce** viene
  **rifiutata (409) prima di toccare il device**: altrimenti risponderebbe al posto di
  quella. Rinominare una telecamera con il **proprio** hostname è permesso.
- La rinomina di una telecamera con `ip:` statico è **invariata**: cambia solo il `name`,
  la voce non acquisisce alcuna chiave `hostname`.

### Scan manuale (diagnostica)

Lo scanner della subnet è per default **solo** uno strumento manuale: il pulsante
"🔍 Rescan subnet" nella dashboard esegue una scansione one-shot su richiesta
dell'operatore. Non viene eseguito all'avvio, e a intervalli **solo** se abiliti
`scan.rescan_time_interval` (vedi sotto). Uno scan salta gli IP già in quarantena (non
ri-tenta credenziali note-errate); un nuovo scan azzera i soli avvisi generati dallo
scan, così l'operatore può rigenerarli.

### Rescan automatico a intervallo (`scan.rescan_time_interval`)

```yaml
scan:
  subnet: 192.168.110.0/24
  rescan_time_interval: 900     # secondi dall'ultimo scan; 0 = disabilitato (default)
```

- **Misurato dall'ULTIMO scan**, manuale o automatico — non su una cadenza fissa. Un
  rescan manuale sposta quindi il prossimo automatico di un intervallo intero, invece di
  farne partire uno pochi secondi dopo.
- **`0` (default) = disabilitato**: comportamento storico invariato, lo scanner parte solo
  dal pulsante.
- **Minimo 60 s** quando > 0: uno scan autentica su *ogni* host della subnet, e un
  intervallo troppo breve è esattamente la raffica di credenziali che fa scattare il
  blocco anti-intrusione Dahua. Un valore inferiore viene alzato a 60 s con un warning.
- **Non parte se uno scan è già in corso** (incluso un rescan manuale in esecuzione).
- **Un rescan automatico NON re-aggiunge una telecamera rimossa dall'operatore.** Uno scan
  avvia un worker per *ogni* device ONVIF che trova, quindi senza questa regola una
  rimozione dalla dashboard verrebbe annullata entro un intervallo e la telecamera
  ricomparirebbe da sola (con le sue entità MQTT/HA). Il **rescan manuale** invece le
  riscopre tutte: è l'operatore che lo chiede esplicitamente. La lista delle rimozioni
  vive in memoria (si azzera al riavvio del servizio e ad ogni rescan manuale).
- Con la password ancora al placeholder lo scan resta soppresso, automatico compreso.
- Modificabile a caldo via `POST /api/config` (`rescan_time_interval`); `GET /api/status`
  espone `rescan_interval` e `rescan_in` (secondi al prossimo scan, `null` se disabilitato).
- **Attenzione al traffico**: se hai anche telecamere configurate per `hostname:`, la
  risoluzione hostname fa già una sua scansione ogni 10 minuti. Le due sono indipendenti
  (la risoluzione non tocca `scan_active`), quindi un intervallo breve significa due
  sweep della subnet sovrapposti.

### Avvisi in dashboard

La dashboard mostra due tipi di avviso legati alle credenziali:

- **⚠️ Password da configurare** (giallo) — la password comune o quella di scan è ancora
  il placeholder `default_to_change`: nessun worker parte e lo scan è disabilitato.
- **⛔ Login telecamera fallito** (rosso) — una o più telecamere hanno rifiutato le
  credenziali e sono in **quarantena** (retry sospesi per non farle bloccare). L'avviso
  elenca IP/nome e la via del fallimento; nella tabella la telecamera compare con stato
  `⛔ login fallito`. Correggi la password in `.env` (`CAMERA_PASSWORD` / `SCAN_PASSWORD`)
  e **riavvia** il servizio.

---

## File di stato

### `/data/alarm.json`

Scritto atomicamente ad ogni cambio di stato allarme.

```json
{
  "saved_at": "2026-06-22T23:00:00",
  "STANZA-11": "on"
}
```

Il nome della chiave corrisponde al nome host ONVIF della telecamera (underscore convertiti in trattini per conformità DNS).

### `settings.yaml`

Unico store di configurazione runtime (sostituisce il vecchio `config.json`).
Letto **e scritto** dall'app: le modifiche dalla pagina Impostazioni sono salvate qui
e persistono tra i riavvii. Il mount di questo file in `docker-compose.yml` deve
essere **read-write** (non `:ro`).

```yaml
mqtt:
  host: localhost          # broker (stringa vuota = MQTT disabilitato)
  port: 1883
  user: ""
  pass: ""
  prefix: onvif
scan:
  subnet: 192.168.110.0/24 # subnet per lo scan (manuale, rescan automatico, risoluzione hostname)
  concurrency: 48          # probe paralleli
  rescan_time_interval: 0  # 0 = nessun rescan automatico; se > 0, minimo 60s
  # La credenziale dello scan è in .env (SCAN_USER / SCAN_PASSWORD), non qui.
cameras:
  credentials:
    port: 80               # comune a tutte; user/pass sono in .env
  list:
    - ip: 192.168.110.248  # indirizzo fisso
      name: SOGGIORNO
    - hostname: STANZA_11  # oppure hostname ONVIF, risolto a runtime
      name: CUCINA
web:
  asset_version: "1"       # token cache-busting asset statici (la password è in .env)
  port: 8081
tuning:                    # vedi "Sensore fall_sensor_online"
  liveness_mode: heartbeat
  heartbeat_interval: 15
serena: {}                 # vedi "Bridge verso Serena"
```

> Le telecamere di produzione si configurano nel blocco `cameras` (solo `port` +
> `list`; la credenziale comune è in `.env`), **non** nel blocco `scan`, che serve
> alla subnet da scansionare. Le password non stanno mai in `settings.yaml`.
>
> **Attenzione ai commenti**: l'app riscrive il file con `yaml.safe_dump`, quindi un
> salvataggio dalla pagina Impostazioni (o una rinomina/rimozione telecamera)
> **elimina tutti i commenti** — le chiavi e i valori restano. Tieni la copia
> commentata di riferimento in `settings.yaml.example` e non nel file vivo.
>
> L'IP risolto di una voce `hostname:` non viene **mai** scritto qui: resta in memoria
> e va ri-risolto ad ogni avvio (vedi "Telecamere per hostname").

---

## MQTT e Home Assistant Discovery

Quando MQTT è configurato e arriva il primo allarme, il container pubblica automaticamente il topic di discovery:

```
homeassistant/binary_sensor/onvif_fall_<nome>/config
```

Home Assistant crea l'entità `binary_sensor.<nome>` con:
- **Device class**: `safety` → mostra *Unsafe* / *Safe*
- **Icona**: `mdi:account-injury`
- **Disponibilità**: gestita da `expire_after` — se il container si ferma e lo stato
  non viene ripubblicato entro la finestra, HA vede il sensore come unavailable
  (non c'è più un topic di disponibilità/LWT globale)

Stato pubblicato su:
```
onvif/<NOME_CAM>/alarms/fall     →  "on" (caduta rilevata) / "off"   (retain=True, QoS=1)
```

### Sensore `fall_sensor_online` (liveness del rilevamento)

Per ogni telecamera configurata viene pubblicato un secondo `binary_sensor` che
indica se il rilevamento caduta è **attivo/funzionante**:

```
homeassistant/binary_sensor/onvif_detect_ok_<nome>/config
onvif/<NOME_CAM>/camera_status/fall_sensor_online        →  "on" / "off"
onvif/<NOME_CAM>/camera_status/fall_sensor_online/attrs  →  {stream_alive, rule_enabled, liveness_mode}
```

Il sensore usa `device_class: connectivity` con **polarità intuitiva**: `on` = rilevamento
**attivo**, `off` = non attivo. (Sostituisce il vecchio sensore `detection_ok` che
invertiva la polarità come `safety`.)

| `stream_alive` | `rule_enabled` | rilevamento | stato MQTT | Home Assistant |
|----------------|----------------|-------------|------------|----------------|
| alive          | true           | attivo      | `on`       | **Online**     |
| alive          | unknown        | attivo      | `on`       | **Online**     |
| alive          | false          | KO (regola disabilitata) | `off` | **Offline** |
| not-alive      | *              | KO (stream giù)          | `off` | **Offline** |

Cioè: **attivo (`on`)** quando lo stream è vivo **e** la regola non è confermata disabilitata.
Uno stato `rule_enabled` `unknown` (errore transitorio del check, o finestra iniziale
prima del primo check) **non** fa passare a "off" se lo stream è vivo. Il sensore usa
`expire_after`; un loop di ripubblicazione periodica (≤ `expire_after/2`) mantiene fresco
lo stato di una telecamera sana.

**Segnali:**
- **`stream_alive`** — heartbeat sullo stream `eventManager.cgi?action=attach&heartbeat=N`.
  Il read-timeout finito di `HEARTBEAT_GAP_FACTOR × N` è il watchdog: un silenzio totale
  (nessun heartbeat né evento) più lungo della soglia segna lo stream come non-vivo, poi
  riconnette. Se il firmware non onora `heartbeat=N`, impostare `LIVENESS_MODE=keepalive`:
  la liveness è guidata da una probe autenticata periodica (`magicBox.cgi`) e non dagli
  eventi (una casa tranquilla senza cadute non deve mai risultare non-viva).
- **`rule_enabled`** — check periodico via `configManager.cgi` che conferma che la regola
  TumbleDetection/StereoBehavior sia presente e abilitata. Errori transitori → `unknown`
  (mai `false`).

---

## Bridge verso Serena (assistente vocale) — opzionale

Oltre a pubblicare lo stato della caduta su Home Assistant, ONVIF_SUA può **inoltrare
la caduta a [Serena](https://…) (alexa-custom)** così che l'assistente vocale chieda a
voce *"Ho rilevato una persona caduta sul sensore … vuoi che chiami aiuto?"* e, su
conferma (o come fail-safe se nessuno risponde), avvii una chiamata LiveKit. Il bridge
**non richiede alcuna modifica al codice di Serena**: riusa il client MQTT già connesso
e pubblica sui topic di comando che Serena già ascolta.

> **Prerequisito**: ONVIF_SUA e Serena devono usare **lo stesso broker MQTT**, e
> `serena.node_id` deve combaciare con il `node_id` di Serena (di default il suo
> hostname, oppure l'override in `state.yaml`). Se `serena.node_id` non è impostato,
> ONVIF_SUA usa l'hostname della propria board — che combacia automaticamente quando
> i due servizi girano sulla stessa board. È un contratto fire-and-forget: ONVIF
> conferma la consegna **al broker**, non che Serena abbia ricevuto/agito.

### Blocco di configurazione `serena:`

Opt-in — disabilitato di default. In `settings.yaml` (autoritativo) o via variabili
d'ambiente `SERENA_*` (default). I flag booleani accettano `1/true/yes/on`
(case-insensitive); ogni altro valore, stringa vuota inclusa, è `false`.

```yaml
serena:
  enabled: false                       # interruttore generale
  topic_prefix: alexa                  # topic_prefix di Serena
  node_id: ""                          # node_id di Serena; vuoto = hostname di questa board
  command_template: "caduta_{cam_name}"         # comando di caduta → <prefix>/<node_id>/trigger/run
  announce_ready: true                 # annuncia "…attivo" una volta per camera quando è confermata operativa
  announce_template: "sensore uomo a terra {cam_name} attivo"
  announce_fault: false                # opt-in: ripete "…non attivo" per un sensore guasto
  announce_fault_template: "attenzione, sensore uomo a terra {cam_name} non attivo"
  announce_fault_interval_s: 300       # cadenza di ripetizione mentre è guasto (minimo 30s)
  announce_fault_grace_s: 60           # sopprime il primo guasto finché non-operativo da almeno tot
  startup_alarm_max_age_s: 300         # adotta una caduta in corso persistita di recente al riavvio
```

Solo `{cam_name}` è ammesso nei tre template; un placeholder sconosciuto o graffe
malformate loggano un warning al caricamento e ricadono sul default. `interval` sotto
30s viene alzato a 30s; `grace: 0` disabilita la finestra di soppressione (possibili
falsi "non attivo" all'avvio) e logga un warning.

### Cosa pubblica

| Evento | Topic | Payload | retain |
|--------|-------|---------|--------|
| **Caduta (start)** | `<prefix>/<node_id>/trigger/run` | `caduta_<stanza>` | `false`, QoS 1 |
| **Sensore attivo** (una volta per camera, quando confermata operativa) | `<prefix>/<node_id>/tts/set` | `sensore uomo a terra <stanza> attivo` | `false`, QoS 1 |
| **Sensore guasto** (opt-in, ripetuto) | `<prefix>/<node_id>/tts/set` | `attenzione, sensore uomo a terra <stanza> non attivo` | `false`, QoS 1 |
| **Ripristino** (dopo ≥1 guasto) | `<prefix>/<node_id>/tts/set` | `sensore uomo a terra <stanza> attivo` | `false`, QoS 1 |

Note importanti:
- Il comando di caduta è emesso **esattamente una volta per evento**, sul fronte
  `TumbleDetection action=start` (i keepalive e le ripubblicazioni su riconnessione non
  lo riemettono; essendo non-retained, una riconnessione di Serena non lo rigioca).
- L'annuncio **attivo** scatta solo quando il sensore è **realmente confermato**
  (stream vivo **e** regola confermata abilitata, `rule_enabled is True` — non basta
  `detection_ok=='on'`, che è `on` anche con `rule_enabled == "unknown"`).
- L'annuncio **guasto** è opt-in, multi-shot, per-camera e indipendente; copre anche
  telecamere mai connesse (driver periodico su tutte le camere configurate). Su
  ripristino pronuncia l'annuncio attivo una volta (il ripristino è gestito da
  `announce_fault`, **non** da `announce_ready`).
- Una telecamera **simulata** è sempre trattata come operativa: annuncia "attivo" e non
  produce mai un guasto.
- **Caduta in corso al riavvio**: se ONVIF_SUA si riavvia mentre una caduta è ancora
  attiva (persistita `"on"` in `alarm.json`), alla prima riconnessione dello stream il
  comando di caduta viene **riemesso una volta** — così una caduta iniziata prima del
  riavvio non va persa (Serena è l'unico responder). L'adozione è **recency-gated**: scatta
  solo se lo stato persistito è stato salvato entro `startup_alarm_max_age_s` (default
  300s); un `"on"` più vecchio è considerato stantìo e **non** riemette.

### Nome telecamera → frase vocale

Il nome viene **normalizzato al momento della resa** (minuscolo, `-`/`_` → spazio,
spazi collassati) prima di finire nel comando e negli annunci. Nel **comando di caduta**
gli spazi diventano poi `_`, così il payload resta un token unico e non pronunciabile:
`salotto-1` → `caduta_salotto_1` (gli annunci vocali restano `salotto 1`, leggibili da
Piper). Il nome memorizzato e il topic di stato `onvif/<cam>/alarms/fall`
**non** cambiano. Un nome **non può contenere** la parola `camera` (case-insensitive,
blocca anche `telecamera`) e non può **collidere** (dopo normalizzazione) con un'altra
telecamera: la rinomina/salvataggio dalla web UI rifiuta il nome con un alert e non lo
applica (né al device né a `settings.yaml`). Usa nomi di stanza (`cucina`, `salotto`).

### Lato Serena (solo config, nessun codice)

La risposta è interamente autorabile in `conf/actions/user.yaml` di Serena come trigger
`with_wake: false` — **uno per telecamera**, con `commands` uguale alla frase
normalizzata. Esempio completo (copia-incolla, poi Serena ricarica a caldo):

```yaml
triggers:
  - commands:
      - "caduta_cucina"        # = command_template reso con il nome normalizzato
    with_wake: false
    tag: sos
    actions:
      - type: ask
        text: "Ho rilevato una persona caduta sul sensore di cucina. Vuoi che chiami aiuto?"
        lang: "it-IT"
        timeout: 8.0
        on_reply:
          - commands: ["si", "sì", "va bene", "certo", "ok", "aiuto"]
            actions:
              - type: say
                text: "Va bene, sto chiamando aiuto"
              - type: livekit_join
              - type: telegram
                text: "Caduta rilevata in cucina — collegati: <room>"
          - commands: ["no", "no grazie", "annulla", "sto bene"]
            actions:
              - type: say
                text: "Va bene, chiamata annullata"
        on_else:
          # Nessuna risposta / non capito → richiedi una volta…
          - type: ask
            text: "Non ho capito. Vuoi che chiami aiuto?"
            lang: "it-IT"
            timeout: 8.0
            on_reply:
              - commands: ["si", "sì", "va bene", "certo", "ok", "aiuto"]
                actions:
                  - type: say
                    text: "Va bene, sto chiamando aiuto"
                  - type: livekit_join
                  - type: telegram
                    text: "Caduta rilevata in cucina — collegati: <room>"
              - commands: ["no", "no grazie", "annulla", "sto bene"]
                actions:
                  - type: say
                    text: "Va bene, chiamata annullata"
            on_else:
              # …e se ancora silenzio, chiama comunque (fail-safe).
              - type: say
                text: "Non ho ricevuto risposta, chiamo aiuto"
              - type: livekit_join
              - type: telegram
                text: "Caduta rilevata in cucina, nessuna risposta — collegati: <room>"
```

Duplica il blocco per ogni telecamera cambiando la frase in `commands` e i testi.
Lo stesso esempio è nel file `conf.example/actions/user.yaml` di Serena.

### Diagnostica e messa in servizio

- **Log di avvio**: quando il bridge è abilitato e configurato, all'inizializzazione
  viene loggato **una volta** il topic risolto `<prefix>/<node_id>/trigger/run` —
  confrontalo con il `node_id` reale di Serena.
- **Entità diagnostica** (retained): un `binary_sensor` HA
  `onvif/serena_bridge/status` riporta se il bridge è connesso al broker; gli attributi
  includono `enabled`, `target_topic`, `node_id`. Non afferma mai che Serena abbia
  ricevuto un comando.
- **Verifica con `mosquitto_sub`**: sul broker, mentre provochi una caduta di test
  (o usi il pulsante *simula* in dashboard), esegui:
  ```bash
  mosquitto_sub -v -t 'alexa/#'
  ```
  e conferma che arrivi la frase esatta su `<prefix>/<node_id>/trigger/run`.
- **Limite residuo**: la consegna è confermata solo **fino al broker**, non fino a
  Serena (nessun ack lato Serena, per scelta di design).

---

## Avvio rapido

L'applicazione è il pacchetto Python **`onvif_sua`** (ex `app.py` monolitico) ed è
eseguibile in due modi, **entrambi con lo stesso identico verbo di install
`uv sync --frozen`** (installa dal lockfile committato, quindi Docker e nativo
risolvono le **stesse** versioni):

1. **Nativo (uv)** — `uv venv --python 3.13` + `uv sync --frozen`, poi
   `uv run onvif-sua` (o `uv run python -m onvif_sua`).
2. **Docker** — l'immagine esegue `uv sync --frozen` (progetto **editable** + deps
   frozen) e avvia lo stesso entrypoint `onvif-sua`.

### Prerequisiti

- **Nativo**: [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`) — scarica Python 3.13 se assente.
- **Docker**: Docker + Docker Compose.
- Broker MQTT Mosquitto raggiungibile (opzionale ma consigliato per HA).
- (Opzionale) [go-task](https://taskfile.dev) per il `Taskfile.yml` unificato.

### Configurazione minima

Crea la cartella `data/`:
```bash
mkdir -p data
```

Crea/verifica `settings.yaml`: imposta il broker MQTT (`mqtt`), la subnet dello scan
manuale (`scan`) e la lista telecamere con la `port` comune (`cameras`). MQTT è poi
modificabile anche dalla GUI. Il `settings.yaml` committato include un'intestazione
commentata con lo schema di esempio; **nessuna password va qui** (stanno in `.env`).

Crea `.env` (copiando `.env.example`) e imposta le password: `CAMERA_PASSWORD`
(credenziale comune telecamere), `SCAN_PASSWORD` (opzionale, default = quella delle
telecamere) e `GUI_PASSWORD` (login web). `.env` è git-ignored e viene caricato sia
in modalità nativa (`uv run`, via python-dotenv) sia in Docker (`env_file: .env`).
Finché `CAMERA_PASSWORD` resta il placeholder `default_to_change` (o non è impostata),
nessuna telecamera viene connessa e lo scan manuale è disabilitato.

### Avvio — nativo (uv)

```bash
uv venv --python 3.13     # crea .venv (uv scarica 3.13 se serve)
uv sync --frozen          # installa dal lockfile committato (progetto editable + deps)
uv run onvif-sua          # oppure: uv run python -m onvif_sua
```

### Avvio — Docker

```bash
docker compose up -d --build
```

Dopo la **prima** build, poiché il progetto è installato **editable** e la sorgente
`./onvif_sua` è bind-montata, una modifica al codice si applica con un semplice
`docker compose restart` — **senza rebuild**. Solo i cambi di *dipendenze*
(`uv lock` + nuova build) richiedono un rebuild.

### Taskfile (opzionale, unifica i due modi)

```bash
task setup          # uv venv + uv sync --frozen
task run            # uv run onvif-sua
task build          # wheel + sdist in dist/ + refresh requirements.lock
task docker:build   # docker compose build
task docker:up      # docker compose up -d
task docker:logs    # docker compose logs -f
task docker:restart # docker compose restart (dev-loop senza rebuild)
task --list         # elenco completo
```

### Logs

```bash
docker compose logs -f
```

### Cache degli asset statici (`web.asset_version`)

CSS/JS sono serviti come `/static/<file>?v=<asset_version>`, dove `asset_version` è
la chiave `web.asset_version` di `settings.yaml` (default `"1"`). Dopo aver
modificato CSS/JS, **incrementa `web.asset_version`** (es. `"1"` → `"2"`) e riavvia:
ogni URL cambia e i pannelli kiosk a lunga esecuzione ri-scaricano gli asset. Senza
l'incremento un kiosk può continuare a servire la copia in cache finché non si forza
un hard-reload.

---

## Pacchetto wheel e installazione con pip (terzo modo)

Oltre a *nativo (uv)* e *Docker*, il progetto si può impacchettare in un **wheel**
standard e installare con `pip` su un altro PC — utile quando sul target non c'è né
Docker né `uv`, ma solo Python 3.13.

### Costruire il pacchetto

Un solo comando produce gli artefatti e aggiorna il file di pin:

```bash
task build          # oppure, senza go-task, i due comandi sotto
```

equivalente a:

```bash
# 1) pin esatto del grafo dipendenze da uv.lock (progetto escluso: lo fornisce il wheel)
uv export --frozen --no-emit-project --no-dev --no-hashes -o requirements.lock
# 2) build di wheel + sdist in dist/
uv build
```

Risultato in `dist/`:

| File                                   | Cos'è                                             |
|----------------------------------------|---------------------------------------------------|
| `onvif_sua-1.0.0-py3-none-any.whl`     | il wheel (codice **+** template/static della web UI) |
| `onvif_sua-1.0.0.tar.gz`               | source distribution (opzionale)                   |
| `requirements.lock`                    | constraints con le versioni **esatte** da `uv.lock` |

Il wheel contiene **solo il codice** (moduli Python + `web/templates` + `web/static`,
grazie ai glob `package-data` di `pyproject.toml`). **Non** contiene `settings.yaml`,
`.env` né `data/`: sono configurazione/segreti/stato e vanno forniti sul target.

### Installare sul PC di destinazione (Python 3.13)

```bash
# porta sul target: il .whl, requirements.lock e settings.yaml.example
cd serena/onvif_sua
source .venv/bin/activate
uv pip install dist/onvif_sua-1.0.0-py3-none-any.whl -c requirements.lock
```

Il flag `-c requirements.lock` **vincola** le dipendenze alle stesse versioni risolte
da `uv`/Docker: senza di esso `pip` risolverebbe i *range* di `pyproject.toml` e
potrebbe installare versioni più recenti. Passa quindi sempre il constraints file per
installazioni riproducibili sulla flotta.

Poi, nella cartella da cui avvii il servizio, prepara i file di runtime (il wheel è
codice, non li include):

```bash
# settings.yaml  → cp settings.yaml.example settings.yaml, poi adattalo
#                  (non contiene password; l'app lo riscrive e ne perde i commenti,
#                   quindi tieni .example come riferimento)
# .env           → crea da .env.example e imposta CAMERA_PASSWORD / GUI_PASSWORD / ...
mkdir -p data
onvif-sua                    # l'entry-point installato dal wheel
```

I path di default sono relativi alla CWD (`settings.yaml`, `data/events.json`,
`data/alarm.json`); per posizioni diverse imposta `SETTINGS_FILE` / `RESULTS_FILE` /
`ALARM_FILE` (vedi la tabella variabili d'ambiente più sotto). Per l'avvio automatico
al boot, avvolgi `onvif-sua` in un servizio `systemd`.

> Nota: il target deve essere **Python ≥ 3.13** (`requires-python`). Il wheel è
> `py3-none-any` (puro Python), quindi non è legato a una piattaforma; sono le
> dipendenze binarie (lxml, ecc.) a essere scaricate come wheel per l'OS del target.

---

## Avvio automatico al boot senza Docker (systemd)

Per far partire il servizio all'accensione su un host Linux **senza Docker**, usa il
unit file `onvif-sua.service` incluso nel repo. La procedura sotto usa l'installazione
via wheel (sezione precedente) nel layout consigliato `/opt/onvif-sua`.

> **Scorciatoia (`task install:systemd`)** — se sul target hai `go-task` e Python 3.13,
> i passi 1–4 sono automatizzati. Copia sul target il repo con la cartella `dist/`
> (wheel prodotto da `task build` sulla macchina di packaging) e `requirements.lock`, poi:
> ```bash
> task install:systemd                 # default: PREFIX=/opt/onvif-sua, SVC_USER=onvif, PY=python3.13
> # override: task install:systemd PREFIX=/srv/onvif SVC_USER=camsvc PY=python3.13
> ```
> Il task crea utente+cartelle, installa il wheel vincolato a `requirements.lock`, copia
> `settings.yaml`/`.env` **senza sovrascrivere** eventuali file esistenti (`cp -n`, così i
> segreti non si perdono), installa il unit e fa `daemon-reload`. **Non** avvia il servizio:
> ti ricorda di impostare le password reali in `.env` e poi `systemctl enable --now`.
> I passi manuali qui sotto restano la referenza (e servono se non usi go-task).

### 1. Layout e utente dedicato

```bash
# utente di servizio non-root (nessuna porta privilegiata: la web UI è la 8081)
sudo useradd --system --home /opt/onvif-sua --shell /usr/sbin/nologin onvif
sudo mkdir -p /opt/onvif-sua/data
```

### 2. Installa il pacchetto nel venv

```bash
# crea il venv (Python 3.13) e installa il wheel VINCOLATO al constraints file
sudo python3.13 -m venv /opt/onvif-sua/.venv
sudo /opt/onvif-sua/.venv/bin/pip install \
    /percorso/onvif_sua-1.0.0-py3-none-any.whl -c /percorso/requirements.lock
```

### 3. Configurazione e segreti

```bash
sudo cp settings.yaml /opt/onvif-sua/settings.yaml     # config (senza password)
sudo cp .env.example  /opt/onvif-sua/.env              # poi EDITA le password reali
sudo chmod 600 /opt/onvif-sua/.env                     # i segreti non leggibili da altri
sudo chown -R onvif:onvif /opt/onvif-sua               # tutto all'utente di servizio
```

> Il servizio risolve `settings.yaml` e `data/` **relativi alla WorkingDirectory**
> (`/opt/onvif-sua`). python-dotenv trova `.env` risalendo dalla posizione del pacchetto:
> in questo layout `.env` è un antenato di `.venv`, quindi viene caricato in automatico.
> Se installi il venv **fuori** da `/opt/onvif-sua`, il `.env` non verrebbe trovato:
> scommenta `EnvironmentFile=-/opt/onvif-sua/.env` nel unit per farlo iniettare da
> systemd. Se usi una cartella diversa, aggiorna
> `WorkingDirectory`/`ExecStart`/`ReadWritePaths` (e l'eventuale `EnvironmentFile`) nel unit.

### 4. Installa e avvia il servizio

```bash
sudo cp onvif-sua.service /etc/systemd/system/onvif-sua.service
sudo systemctl daemon-reload
sudo systemctl enable --now onvif-sua        # abilita al boot + avvia subito
```

### 5. Verifica

```bash
systemctl status onvif-sua        # stato + ultime righe
journalctl -u onvif-sua -f        # log in tempo reale (equivalente a docker logs -f)
```

La web UI è su `http://<host>:8081/`. Il servizio si riavvia da solo su crash
(`Restart=on-failure`) e riparte ad ogni boot.

### Aggiornamenti

```bash
sudo /opt/onvif-sua/.venv/bin/pip install --upgrade \
    /percorso/onvif_sua-<nuova>.whl -c /percorso/requirements.lock
sudo systemctl restart onvif-sua
```

### Disinstallazione

```bash
task uninstall:systemd                 # ferma+disabilita il servizio, rimuove il unit
# per cancellare ANCHE config/.env/data e l'utente:
task uninstall:systemd PURGE=true
```

Senza `PURGE=true` la cartella `/opt/onvif-sua` (config, `.env` con i **segreti**, `data/`)
viene **conservata**, così una reinstallazione riparte dalla stessa configurazione.
Equivalente manuale del solo distacco del servizio:

```bash
sudo systemctl disable --now onvif-sua
sudo rm /etc/systemd/system/onvif-sua.service
sudo systemctl daemon-reload
```

### Variante: installazione nativa con `uv` (checkout del repo)

Se sul target hai `uv` e il checkout del repo invece del wheel, nel unit sostituisci
`ExecStart` (righe alternative già commentate nel file):

```ini
WorkingDirectory=/opt/onvif-sua                       # la cartella del repo (con pyproject.toml)
ExecStart=/usr/local/bin/uv run --frozen onvif-sua    # usa `which uv` per il path esatto
```

e assicurati di aver eseguito `uv sync --frozen` una volta in quella cartella.

---

## docker-compose.yml

```yaml
services:
  onvif-events:
    build: .
    network_mode: "host"
    volumes:
      # SOLO la sorgente del pacchetto, montata RO. L'immagine installa onvif_sua
      # editable, quindi questo mount È il codice che gira: le modifiche si applicano
      # con `docker compose restart` (no rebuild). NON montare sopra /app (nasconderebbe
      # /app/.venv e /app/pyproject.toml).
      - ./onvif_sua:/app/onvif_sua:ro
      # File config (MQTT, scan, lista cameras) — RW così la GUI può salvarlo
      - ./settings.yaml:/app/settings.yaml
      - ./data:/data
    # Le password (telecamere / scan / login GUI) stanno in .env, git-ignored.
    env_file:
      - .env
    environment:
      # Solo process/path. Tutto il tuning (liveness, heartbeat, rule-check,
      # keepalive, save_interval, porta web, concorrenza scan) e MQTT/scan/cameras
      # stanno in settings.yaml — un'unica superficie di config condivisa da nativo e Docker.
      - TZ=Europe/Rome
      - PYTHONUNBUFFERED=1
      - SETTINGS_FILE=/app/settings.yaml
      - RESULTS_FILE=/data/events.json
      - ALARM_FILE=/data/alarm.json
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "20m"
        max-file: "3"
```

> **Nota**: `network_mode: host` è necessario per raggiungere le telecamere sulla rete locale e per la connessione al broker MQTT.
> Il broker MQTT si configura nel blocco `mqtt` di `settings.yaml`, non più tramite variabili d'ambiente.

---

## Rinomina telecamera

Dalla dashboard, icona ✏️ accanto al nome → inserisci il nuovo nome.  
Il nome viene inviato alla telecamera tramite ONVIF `SetHostname`.

**Limitazione**: le telecamere Dahua accettano solo nomi DNS-validi (lettere, cifre, trattini). Gli underscore vengono convertiti automaticamente in trattini.

**Se la telecamera è configurata per `hostname:`** la rinomina cambia proprio il valore
su cui si basa la risoluzione, quindi riscrive anche `hostname:` nella sua voce di
`settings.yaml` (usando l'hostname che il device riporta dopo la scrittura) e rifiuta
con 409 un nome uguale all'`hostname` di un'altra voce. Il worker non viene riavviato:
l'IP non è cambiato. Dettagli e conseguenze in
[Rinomina di una telecamera configurata per hostname](#rinomina-di-una-telecamera-configurata-per-hostname).

---

## Configurazione: `settings.yaml` vs variabili d'ambiente

**Precedenza**: il valore in `settings.yaml` è **autoritativo** e sovrascrive la
variabile d'ambiente corrispondente; l'env fornisce solo il *default* quando la
chiave manca. Questo vale in **entrambe** le modalità (nativo e Docker), così c'è
un'unica superficie di config.

**In `settings.yaml`**: broker MQTT (`mqtt`), subnet + concorrenza scan + intervallo
del rescan automatico (`scan`: `subnet`, `concurrency`, `rescan_time_interval`), porta
web + `asset_version` (`web`), lista telecamere (`ip:` o `hostname:`) + `port` comune
(`cameras`), e il **tuning liveness** (`tuning`: `liveness_mode`,
`heartbeat_interval`, `heartbeat_gap_factor`, `rule_check_interval`,
`keepalive_interval`, `save_interval`).

**Nel file `.env`** (vedi `.env.example`, git-ignored, caricato da python-dotenv in
nativo e da `env_file` in Docker) — **le uniche password del sistema**. Una variabile
già esportata nell'ambiente ha la precedenza sul valore in `.env` (`override=False`):

| Variabile          | Default              | Descrizione                                        |
|--------------------|----------------------|----------------------------------------------------|
| `CAMERA_USER`      | `admin`              | Username comune telecamere                         |
| `CAMERA_PASSWORD`  | `default_to_change`  | Password comune telecamere (placeholder = sospeso) |
| `SCAN_USER`        | = `CAMERA_USER`      | Username per gli scan della subnet                 |
| `SCAN_PASSWORD`    | = `CAMERA_PASSWORD`  | Password per gli scan della subnet                 |
| `GUI_PASSWORD`     | `default_to_change`  | Password di login alla web UI                      |

> La credenziale di scan non serve più solo allo scan manuale: la usano anche il
> rescan automatico e la risoluzione hostname→IP. Con la password ancora al
> placeholder tutti e tre restano sospesi.
>
> **La precedenza dell'ambiente è la causa più frequente di "ho cambiato la password e
> non cambia niente"**: se `CAMERA_PASSWORD` è esportata nella shell che avvia il
> servizio, quel valore vince su `.env` e il file viene ignorato. L'avviso all'avvio lo
> dice esplicitamente e suggerisce `unset CAMERA_PASSWORD`.

**Solo variabili d'ambiente** (path infrastrutturali — non possono stare nel file
che indicano). I default sono **relativi alla CWD** così il nativo funziona dalla
repo senza env; Docker imposta i path assoluti `/app`,`/data` in compose:

| Variabile              | Default nativo       | Docker (compose)     | Descrizione                 |
|------------------------|----------------------|----------------------|-----------------------------|
| `SETTINGS_FILE`        | `settings.yaml`      | `/app/settings.yaml` | File di config unico        |
| `RESULTS_FILE`         | `data/events.json`   | `/data/events.json`  | Path file log eventi        |
| `ALARM_FILE`           | `data/alarm.json`    | `/data/alarm.json`   | Path file stato allarmi     |

> Nota: il vecchio `SCAN_INTERVAL` è stato **rimosso**. La scansione periodica esiste
> di nuovo, ma si configura con `scan.rescan_time_interval` in `settings.yaml`
> (env di default: `RESCAN_TIME_INTERVAL`) ed è **disabilitata** a `0`, che è il default.
> I vecchi env di tuning (`WEB_PORT`, `LIVENESS_MODE`, `HEARTBEAT_*`,
> `RULE_CHECK_INTERVAL`, `KEEPALIVE_INTERVAL`, `SAVE_INTERVAL`, `SCAN_SUBNET`,
> `SCAN_CONCUR`, `RESCAN_TIME_INTERVAL`) restano accettati come default, ma il posto
> giusto ora è `settings.yaml` (blocchi `tuning`/`scan`/`web`).

---

## Dipendenze Python

Le dipendenze (con i **range** di intento) sono dichiarate in `pyproject.toml`; le
versioni esatte (runtime + transitive) sono **bloccate** nel `uv.lock` committato, che
è la fonte di riproducibilità per entrambi i modi (`uv sync --frozen`). `requirements.txt`
non esiste più.

`requirements.lock` è invece un **constraints file generato** da `uv.lock` (via
`task build` / `uv export`), usato solo per l'installazione via `pip` del wheel
(`pip install …whl -c requirements.lock`) — vedi la sezione *Pacchetto wheel*. Non va
editato a mano: si rigenera ad ogni `task build`.

```
fastapi
uvicorn
onvif-zeep-async
requests
paho-mqtt
PyYAML
jinja2          # richiesto dal web layer (FastAPI Jinja2Templates)
```

Richiede **Python >= 3.13** (`requires-python`). Per rigenerare il lockfile dopo un
cambio di dipendenze: `uv lock` (poi rebuild dell'immagine Docker).

---

## Limite residuo noto: sensore fisicamente compromesso

`detection_ok` prova che lo **stream eventi è vivo** (heartbeat) e che la **regola
analytics è abilitata** (configManager). **Non** rileva una compromissione *fisica*
del sensore che lasci telecamera e regola apparentemente funzionanti:

- obiettivo coperto/ostruito (nastro, mobile, polvere);
- telecamera spostata/inclinata fuori dall'area di calibrazione;
- deriva di calibrazione della StereoBehavior nel tempo.

In questi casi heartbeat e regola restano OK ma una caduta reale potrebbe non essere
rilevata. **Mitigazioni consigliate** (fuori dallo scope di questo servizio):

- ispezione visiva periodica / snapshot pianificato dell'inquadratura di ogni telecamera;
- test di caduta simulata pianificato durante la manutenzione ordinaria;
- verifica fisica del montaggio e della calibrazione ad ogni intervento in loco.

Questo limite è intrinseco a una verifica software-only ed è documentato come rischio
residuo accettato.

---

## Note di sicurezza

- La web UI è protetta da autenticazione (cookie session HMAC). Le API `/alarm.json` e `/api/alarms` sono pubbliche per compatibilità con Home Assistant.
- Non esporre la porta 8081 su internet senza un reverse proxy con TLS.
- Usare una sola credenziale comune per le telecamere (`user`/`pass` in `.env`, `port` nel blocco `cameras` di `settings.yaml`): tentativi multipli con password errata attivano il blocco anti-intrusione Dahua. Il servizio si difende su due livelli: (1) finché la password è il placeholder `default_to_change` **nessun** worker parte e lo scan è disabilitato; (2) con una password reale ma **errata**, al primo 401/403 la telecamera va **in quarantena** e ogni retry si ferma (più un gate di autenticazione all'avvio che sfasa i primi tentativi tra le varie vie). Così anche una password di fleet errata resta ben sotto la soglia anti-intrusione. Recupero: correggi `.env` e riavvia.
