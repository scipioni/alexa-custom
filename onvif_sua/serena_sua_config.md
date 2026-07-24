# ONVIF_SUA ↔ Serena — configurazione dell'integrazione

Come collegare **ONVIF_SUA** (rilevamento caduta Dahua) e **Serena** (assistente
vocale, *alexa-custom*) così che una caduta faccia partire una conferma vocale e,
su conferma o come fail-safe, una chiamata LiveKit.

> **Principio**: nessuna modifica al *codice* di Serena. Il collegamento è
> interamente **MQTT + configurazione**. ONVIF_SUA pubblica su topic che Serena
> già ascolta; Serena reagisce con trigger scritti nel suo YAML.

---

## 1. Architettura del collegamento

```
                MQTT broker condiviso (es. 192.168.1.x:1883)
                              │
   ONVIF_SUA  ───pubblica───► │ ◄───sottoscrive───  Serena (alexa-custom)
   (bridge serena)            │                     node_id = <hostname|override>
                              │
   caduta start ─► <prefix>/<node_id>/trigger/run   : "caduta <stanza>"
   sensore attivo ─► <prefix>/<node_id>/tts/set     : "sensore uomo a terra <stanza> attivo"
   sensore guasto ─► <prefix>/<node_id>/tts/set     : "attenzione, ... non attivo"
```

**Due requisiti irrinunciabili** perché arrivi qualcosa:

1. **Stesso broker MQTT** per entrambi i servizi.
2. **`node_id` combaciante**: il `serena.node_id` di ONVIF_SUA deve essere identico
   al `node_id` di Serena (di default l'hostname del dispositivo Serena, oppure
   l'override impostato nella sua config/`state.yaml` o dal pannello web).

Contratto **fire-and-forget**: ONVIF_SUA conferma la consegna *al broker*, non che
Serena abbia ricevuto/agito (nessun ack lato Serena, per scelta di design).

---

## 2. Lato ONVIF_SUA — blocco `serena:`

Opt-in, **disabilitato di default**. Si configura in `settings.yaml` (autoritativo)
oppure con variabili d'ambiente `SERENA_*` (default). I flag booleani accettano
`1/true/yes/on` (case-insensitive); ogni altro valore, stringa vuota inclusa, è
`false`.

### `settings.yaml` — configurazione minima per abilitare

```yaml
serena:
  enabled: true          # ← accendi il bridge
  topic_prefix: alexa    # = topic_prefix di Serena (default 'alexa')
  node_id: galileo       # ← OBBLIGATORIO: uguale al node_id di Serena
```

Senza `enabled: true`, un `mqtt.host` configurato e un `node_id` non vuoto **non
viene pubblicato nulla**.

### Tutte le chiavi (con i default)

| chiave `serena.` | env var | default | significato |
|---|---|---|---|
| `enabled` | `SERENA_ENABLED` | `false` | interruttore generale |
| `topic_prefix` | `SERENA_TOPIC_PREFIX` | `alexa` | prefisso topic di Serena |
| `node_id` | `SERENA_NODE_ID` | `""` | node_id di Serena (**obbligatorio**) |
| `command_template` | `SERENA_COMMAND_TEMPLATE` | `caduta {cam_name}` | frase di caduta → `trigger/run` |
| `announce_ready` | `SERENA_ANNOUNCE_READY` | `true` | annuncia "…attivo" 1× per camera quando confermata operativa |
| `announce_template` | `SERENA_ANNOUNCE_TEMPLATE` | `sensore uomo a terra {cam_name} attivo` | frase annuncio attivo |
| `announce_fault` | `SERENA_ANNOUNCE_FAULT` | `false` | opt-in: ripete "…non attivo" per un sensore guasto |
| `announce_fault_template` | `SERENA_ANNOUNCE_FAULT_TEMPLATE` | `attenzione, sensore uomo a terra {cam_name} non attivo` | frase annuncio guasto |
| `announce_fault_interval_s` | `SERENA_ANNOUNCE_FAULT_INTERVAL_S` | `300` | cadenza di ripetizione (minimo 30s) |
| `announce_fault_grace_s` | `SERENA_ANNOUNCE_FAULT_GRACE_S` | `60` | attesa prima del primo "non attivo" (0 = disabilita la finestra) |
| `startup_alarm_max_age_s` | `SERENA_STARTUP_ALARM_MAX_AGE_S` | `300` | adotta una caduta in corso persistita di recente al riavvio |

Regole di validazione (al caricamento):
- Nei tre template è ammesso **solo** `{cam_name}`; placeholder sconosciuti o graffe
  malformate → warning nel log e fallback al default.
- `announce_fault_interval_s` sotto 30 → alzato a 30 (con warning).
- `announce_fault_grace_s: 0` → conservato ma con warning (possibili falsi
  "non attivo" all'avvio).

### Cosa pubblica ONVIF_SUA

| Evento | Topic | Payload | retain |
|---|---|---|---|
| Caduta (start) | `<prefix>/<node_id>/trigger/run` | `caduta <stanza>` | `false`, QoS 1 |
| Sensore attivo (1× per camera) | `<prefix>/<node_id>/tts/set` | `sensore uomo a terra <stanza> attivo` | `false`, QoS 1 |
| Sensore guasto (opt-in, ripetuto) | `<prefix>/<node_id>/tts/set` | `attenzione, sensore uomo a terra <stanza> non attivo` | `false`, QoS 1 |
| Ripristino (dopo ≥1 guasto) | `<prefix>/<node_id>/tts/set` | `sensore uomo a terra <stanza> attivo` | `false`, QoS 1 |

Il comando di caduta è **non-retained** ed emesso **una sola volta per evento** (sul
fronte `TumbleDetection start`); una riconnessione di Serena non lo rigioca.

**Caduta in corso al riavvio**: se ONVIF_SUA si riavvia mentre una caduta è ancora attiva
(persistita `"on"` in `alarm.json`), alla prima riconnessione dello stream il comando viene
**riemesso una volta** — così una caduta iniziata prima del riavvio non va persa. L'adozione
è **recency-gated** da `startup_alarm_max_age_s` (default 300s): un `"on"` salvato più tempo
fa è considerato stantìo e non riemette.

### Nome telecamera → frase vocale (importante)

`{cam_name}` è **normalizzato al momento della resa**: minuscolo, `-`/`_` → spazio,
spazi collassati. Esempio: camera `salotto-1` → frase `caduta salotto 1`. Il nome
memorizzato e il topic di stato `onvif/<cam>/alarms/fall` non cambiano.

Vincoli sul nome (applicati da rinomina/salvataggio in dashboard):
- **non può contenere** la parola `camera` (case-insensitive; blocca anche `telecamera`);
- non può **collidere** (dopo normalizzazione) con un'altra telecamera.

Usa nomi di stanza: `cucina`, `salotto`, `letto`, `bagno`.

---

## 3. Lato Serena — `conf/actions/user.yaml` (solo config, nessun codice)

La risposta vocale è **interamente** scritta nel file di trigger di Serena. Serve
**un trigger `with_wake: false` per telecamera**, con `commands` uguale alla frase
emessa da ONVIF_SUA in forma **normalizzata**.

Esempio completo (una telecamera `cucina`); duplica cambiando frase/testo per ogni
camera:

```yaml
triggers:
  - commands:
      - "caduta cucina"        # = command_template reso col nome normalizzato
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
        on_else:                       # nessuna risposta / non capito → richiedi 1×
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
            on_else:                   # ancora silenzio → chiama comunque (fail-safe)
              - type: say
                text: "Non ho ricevuto risposta, chiamo aiuto"
              - type: livekit_join
              - type: telegram
                text: "Caduta rilevata in cucina, nessuna risposta — collegati: <room>"
```

Note:
- I `commands` devono corrispondere alla frase normalizzata. `command_template`
  `caduta {cam_name}` + camera `letto` → `commands: ["caduta letto"]`.
- `<room>` nel testo `telegram` è il placeholder del link stanza di Serena (già
  gestito dall'azione `telegram`).
- Gli annunci "attivo"/"non attivo" arrivano su `tts/set` e vengono pronunciati da
  Serena **senza bisogno di alcun trigger** (Serena sottoscrive già `tts/set`).
- Serena ricarica a caldo `conf/actions/user.yaml` (~ ogni pochi secondi): niente
  riavvio.

### Prerequisiti Serena

- `LIVEKIT_*` e Telegram configurati (le azioni `livekit_join`/`telegram` riusano la
  config esistente di Serena — nessuna nuova config qui).
- Stesso broker MQTT di ONVIF_SUA.

---

## 4. Come trovare / impostare il `node_id` di Serena

Serena calcola `node_id = <override> or socket.gethostname()`. Per allineare
ONVIF_SUA:

- **Opzione A** — leggi il `node_id` effettivo di Serena (config/`state.yaml`,
  pannello web "local node_id", o l'hostname del dispositivo) e mettilo in
  `serena.node_id` di ONVIF_SUA.
- **Opzione B** — osserva i topic reali sul broker (vedi §5) e copia il segmento
  `<node_id>` che vedi passare.

---

## 5. Messa in servizio e verifica

1. **Stesso broker**: verifica che `mqtt.host`/`port` di ONVIF_SUA e di Serena
   puntino allo stesso broker.
2. **Log di avvio ONVIF_SUA**: a bridge abilitato+configurato viene loggato **una
   volta** il topic risolto, es.:
   ```
   [serena] bridge attivo — comando di caduta su 'alexa/galileo/trigger/run'
   ```
   Confrontalo con il `node_id` reale di Serena.
3. **Sniff sul broker** mentre provochi una caduta di test (o usi il pulsante
   *simula* nella dashboard ONVIF_SUA):
   ```bash
   mosquitto_sub -v -t 'alexa/#'
   ```
   Deve comparire `alexa/<node_id>/trigger/run  caduta <stanza>`.
4. **Entità diagnostica** (Home Assistant, retained): `onvif/serena_bridge/status`
   riporta se il bridge è connesso al broker; attributi `enabled`, `target_topic`,
   `node_id`. Non afferma mai che Serena abbia ricevuto il comando.
5. **Serena**: se la frase non combacia con nessun trigger, Serena logga un
   no-match e fa un beep → controlla che `commands` corrisponda alla frase
   normalizzata.

---

## 6. Modifiche effettivamente introdotte (riepilogo)

Queste sono le modifiche di **configurazione** che abilitano l'interoperabilità
(il codice del bridge è documentato nel README di ONVIF_SUA):

**Lato ONVIF_SUA (questo repo):**
- `settings.yaml` — aggiunto il blocco `serena:` commentato (esempio + doc inline).
- `.env.example` — aggiunte le variabili `SERENA_*` corrispondenti (commentate).
- `README.md` — sezione "Bridge verso Serena" con contratto topic/frase, annunci,
  regole di naming e verifica.

**Lato Serena (repo `serena`):**
- `conf.example/actions/user.yaml` — aggiunto un esempio copia-incolla del trigger
  di caduta (`caduta cucina`) con flusso conferma → chiamata + Telegram e fail-safe.
- `AGENTS.md` (= `.claude/CLAUDE.md`) — nota che gli allarmi di caduta arrivano via
  `trigger/run` e sono gestiti **solo** in `conf/actions/user.yaml` (nessun codice
  Serena).

> **Nota**: nessun valore è stato *attivato* in una configurazione live. Il bridge
> resta `enabled: false` di default; per accenderlo, imposta i valori della §2
> (ONVIF_SUA) e aggiungi i trigger della §3 (Serena) sul deployment reale.
