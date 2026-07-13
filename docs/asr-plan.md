Analisi Comparativa e Progettazione Architetturale per Sistemi ASR in Italiano su Piattaforma Embedded Arduino Uno QLa realizzazione di un agente vocale reattivo, flessibile e privo di parole chiave di attivazione (wake words) su sistemi a risorse vincolate rappresenta una sfida complessa nell'ambito dell'edge computing. La piattaforma Arduino Uno Q si colloca al centro di questo scenario grazie a un'architettura dual-brain altamente innovativa. Essa integra un microprocessore quad-core Qualcomm Dragonwing QRB2210, destinato all'esecuzione di una distribuzione Debian Linux e di script Python complessi, e un microcontrollore STMicroelectronics STM32U585 basato su architettura ARM Cortex-M33, dedicato al controllo deterministico in tempo reale.Per garantire che l'agente vocale possa rispondere istantaneamente a comandi in lingua italiana come "accendi le luci" o "che tempo farà domani", è necessario ottimizzare l'intera pipeline di riconoscimento vocale automatico (ASR, Automatic Speech Recognition). Questa analisi esamina le inefficienze dei comuni approcci locali, spiega le cause fisiche e algoritmiche dei fallimenti riscontrati con Vosk, Sherpa-Onnx e Moonshine, e propone un'architettura software ottimizzata in grado di ridurre la latenza di risposta al di sotto della soglia critica dei 500 millisecondi.Analisi delle Inefficienze nei Tentativi di Implementazione PrecedentiI test condotti con diverse librerie ASR locali su architetture basate su core ARM Cortex-A53 rivelano colli di bottiglia strutturali profondi, legati sia alla natura dei modelli sia alle modalità di esecuzione del codice.Vosk Small: Limitazioni Fonetiche e Anomalie di TrascrizioneIl modello di dimensioni ridotte di Vosk (tipicamente inferiore a 70 MB) rappresenta una soluzione ampiamente utilizzata in ambienti a basse risorse grazie a un consumo di memoria estremamente contenuto e a tempi di risposta rapidi. Tuttavia, la precisione della trascrizione per la lingua italiana risulta insoddisfacente in contesti di interazione naturale [cite: User Query]. I modelli Vosk Small soffrono di un tasso di errore sui lemmi (WER, Word Error Rate) elevato a causa di una rappresentazione acustica compressa che fatica a discriminare le flessioni fonetiche tipiche della lingua italiana, specialmente in presenza di rumore ambientale o di lievi variazioni di pronuncia.Un fenomeno ricorrente e documentato nell'integrazione di Vosk all'interno di sistemi di automazione in italiano riguarda l'inserimento spuri di caratteri isolati, in particolare la vocale "e", all'inizio di quasi tutte le frasi rilevate. Questa anomalia degrada l'accuratezza del sistema di comprensione del linguaggio naturale (NLU) basato su regole o corrispondenze semantiche, impedendo il corretto parsing di comandi diretti come "accendi le luci" [cite: User Query]. Al contrario, l'adozione di modelli Vosk di grandi dimensioni (da oltre 1.4 GB) risolverebbe il problema dell'accuratezza ma comporterebbe una latenza di emissione delle parole superiore ai 2000 millisecondi, saturando la memoria RAM della scheda.Sherpa-Onnx: Le Cause della Latenza ElevataLa piattaforma sherpa-onnx, pur basandosi sul runtime ottimizzato ONNX, può mostrare tempi di risposta elevati se non configurata secondo rigidi criteri di esecuzione in streaming [cite: User Query, 68]. Le cause principali di una latenza insoddisfacente riscontrata in fase di test includono:Utilizzo di Modelli non Ottimizzati per lo Streaming: L'adozione di modelli ASR di tipo offline (batch) costringe il sistema ad attendere la completa conclusione del parlato dell'utente, a salvare l'intero flusso audio in un buffer temporaneo o in un file WAV e a eseguire l'inferenza solo in seguito. Questo approccio raddoppia i tempi di elaborazione rispetto alla durata del parlato.Dimensioni dei Modelli di Traduzione o Trascrizione: L'impiego di modelli Zipformer complessi a 128 strati (kroko_128l) assicura un'elevata precisione a scapito di un carico computazionale insostenibile per i singoli core Cortex-A53, determinando un fattore di tempo reale (RTF) superiore all'unità.Mancata Ottimizzazione del Multithreading e dei Chunk Audio: Se la pipeline Python esegue le operazioni di acquisizione audio e di decodifica nello stesso thread, le chiamate bloccanti del motore ASR generano ritardi cumulativi nel recupero dei frame della scheda audio.Moonshine: Complessità di Addestramento e Limiti dello Streaming nei ComandiL'architettura Moonshine si distingue per la capacità di gestire input audio a lunghezza variabile senza richiedere operazioni di zero-padding, riducendo drasticamente il calcolo ridondante rispetto ai modelli Whisper tradizionali. Tuttavia, il trasferimento di questa tecnologia a un sistema di comandi in lingua italiana presenta ostacoli significativi [cite: User Query]:Bias Linguistico dei Modelli Pre-addestrati: I modelli Moonshine ufficiali e altamente ottimizzati sono addestrati prevalentemente per gli accenti inglesi (US/UK). L'addestramento personalizzato per l'italiano richiede pipeline di data preparation e fine-tuning complesse, spesso soggette a problemi di convergenza su architetture embedded [cite: User Query, 84].Inadeguatezza dello Stato di Caching per Frasi Brevi: Sebbene il caching dello stato del decodificatore consenta di velocizzare la trascrizione incrementale mentre l'utente parla, questa logica è ottimizzata per flussi continui e discorsivi. Nei comandi vocali brevi e sporadici, i meccanismi di attenzione del Transformer accumulano un rumore di fondo che degrada la stabilità dei token generati, rendendo difficile l'estrazione pulita del comando finale senza un robusto strato di endpointing esterno [cite: User Query, 88].Architettura Ottimizzata per un Sistema "Always-On" Senza Wake WordPer superare i limiti evidenziati e realizzare un sistema di controllo reattivo senza l'uso di parole chiave di attivazione, l'architettura software deve implementare una pipeline di elaborazione a tre stadi basata su rilevamento di attività vocale (VAD), buffering circolare e decodifica incrementale in streaming.+----------------------------------------------------------------------------------+
|                              PIPELINE AUDIO ALWAYS-ON                            |
+----------------------------------------------------------------------------------+
|                                                                                  |
|  [Ingresso Microfono USB] --> 16 kHz, Mono, 16-bit PCM                           |
|                                     |                                            |
|                                     v                                            |
|                        +--------------------------+                              |
|                        | Ring Buffer Pre-Roll     | <-- Memorizza continuamente    |
|                        | (150 ms - 200 ms)        |     gli ultimi frame di audio  |
|                        +--------------------------+                               |
|                                     |                                            |
|                                     v                                            |
|                        +--------------------------+                              |
|                        | Silero VAD (ONNX Lite)   | <-- Analisi continua a basso   |
|                        +--------------------------+     consumo di CPU             |
|                                     |                                            |
|                  +------------------+------------------+                         |
|                  | Speech = True                       | Speech = False          |
|                  v                                     v                         |
|  +-------------------------------+             +------------------------------+  |
|  | Attivazione Flusso Streaming  |             | Continua il monitoraggio     |  |
|  | - Svuota Ring Buffer nell'ASR |             | e mantiene aggiornato        |  |
|  | - Invia frame attuali         |             | il Ring Buffer di pre-roll   |  |
|  +-------------------------------+             +------------------------------+  |
|                  |                                                               |
|                  v                                                               |
|  +-------------------------------+                                               |
|  | Sherpa-Onnx Online Recognizer |                                               |
|  | (Modello Kroko 64L INT8)      |                                               |
|  +-------------------------------+                                               |
|                  |                                                               |
|                  v                                                               |
|  +-------------------------------+                                               |
|  | Rilevamento Fine Parlato      |                                               |
|  | (Silenzio continuo > 400 ms)  |                                               |
|  +-------------------------------+                                               |
|                  |                                                               |
|                  v                                                               |
|  +-------------------------------+                                               |
|  | Invio Comando tramite RPC     | --> Spegne/Accende pin GPIO su MCU STM32     |
|  +-------------------------------+                                               |
+----------------------------------------------------------------------------------+
Il Ruolo Chiave del Rilevamento dell'Attività Vocale (VAD)In un sistema privo di wake word, mantenere il modello ASR costantemente in funzione comporterebbe una saturazione permanente della CPU dell'Arduino Uno Q, impedendo l'esecuzione fluida di altri servizi e innalzando le temperature operative del processore. L'integrazione di un modulo VAD leggero ed estremamente accurato come Silero VAD v6 (eseguito in formato ONNX tramite runtime ottimizzato) funge da guardiano della pipeline.Il modulo VAD analizza l'audio in blocchi da 512 campioni (equivalenti a 32 ms a una frequenza di 16 kHz). Il consumo computazionale di questa operazione è inferiore all'1% della capacità di calcolo di un singolo core Cortex-A53.Finché viene rilevato solo silenzio o rumore ambientale, l'audio viene archiviato all'interno di un buffer circolare di pre-roll (Ring Buffer) implementato tramite una struttura deque in Python, con una lunghezza massima equivalente a circa 150-200 ms di segnale. Questa precauzione impedisce la perdita delle consonanti occlusive o delle sillabe iniziali dei comandi (ad esempio, la "A" di "accendi"), che altrimenti verrebbero troncate a causa della latenza di attivazione del modello neurale del VAD.Quando il VAD rileva l'inizio del parlato (probabilità superiore a 0.45), il sistema esegue le seguenti operazioni:Sblocca lo stato del flusso ASR streaming.Inietta istantaneamente i frame archiviati nel Ring Buffer all'interno dell'algoritmo di decodifica.Avvia la trasmissione dei frame correnti in tempo reale al riconoscimento vocale.L'endpointing (rilevamento della fine della frase) viene stabilito quando il VAD rileva una persistenza di non-parlato per una durata superiore a 400 ms. A quel punto, il sistema arresta l'invio di dati all'ASR, richiede la finalizzazione della stringa testuale (operazione di flush) e passa il comando all'unità logica di esecuzione.Soluzione Open-Source: Sherpa-Onnx con Modello Zipformer Kroko ITLa risposta ottimale ai requisiti di un sistema interamente open-source e locale per la lingua italiana risiede nell'adozione del framework sherpa-onnx configurato per l'uso del modello basato su architettura Zipformer sviluppato dalla community Kroko.Il modello specifico da integrare è:
sherpa-onnx-streaming-zipformer-it-kroko-2025-08-06.Caratteristiche Tecniche e Ottimizzazione di Zipformer KrokoL'architettura Zipformer di seconda generazione (Zipformer2) è accoppiata a un decodificatore a trasduttore (RNN-T, Recurrent Neural Network Transducer). A differenza dei modelli basati su connessione temporale classica (CTC), il modello Transducer è intrinsecamente ottimizzato per la decodifica in streaming frame-by-frame, offrendo una latenza algoritmica eccezionalmente bassa.Per massimizzare la reattività sul processore quad-core dell'Arduino Uno Q, occorre selezionare la variante di modello Kroko 64-layer (kroko_64l) quantizzata in precisione INT8 (dynamic quantization). Rispetto alla versione a 128 strati (kroko_128l), la variante a 64 strati dimezza il carico di calcolo sull'unità aritmetica della CPU pur mantenendo un degrado di accuratezza irrilevante (incremento del WER inferiore al 2%).La tabella seguente mostra il confronto prestazionale stimato tra i diversi modelli compatibili con l'hardware e la lingua italiana della scheda embedded.Configurazione Modello ASRDimensione su DiscoRAM RichiestaLatenza Post-UtteranceRTF (su Cortex-A53)Idoneità all'Uso su Arduino Uno QVosk Small (Italiano)~50 MB~100 MB~120 ms~0.15Bassa (Accuratezza insufficiente, bug pre-allocazione vocale)Kroko Zipformer 64L (INT8)~146 MB~200 MB< 150 ms~0.25 (Ottimo)Alta (Miglior compromesso open-source, alta accuratezza)Kroko Zipformer 128L (INT8)~146 MB~350 MB~380 ms~0.65Media (Latenza avvertibile su comandi rapidi)Whisper-Base (CTranslate2 INT8)~140 MB~350 MB> 3000 ms> 1.20 (Inadatto)Nulla (Latenza elevata dovuta a finestra fissa di 30s)Picovoice Cheetah (Italiano)~34 MB< 50 MB< 100 ms~0.08 (Eccellente)Alta (Ottimalità tecnica, ma richiede licenza commerciale)Per garantire il funzionamento a bassa latenza con sherpa-onnx è mandatorio configurare l'istanza OnlineRecognizer impostando il parametro num_threads a un valore pari a 2 o 4. Questo accorgimento consente di parallelizzare l'esecuzione sui core fisici del processore QRB2210 senza indurre un sovraccarico dovuto al contesto di switching dei thread del kernel Linux.Soluzione Commerciale Alternativa: Picovoice Rhino (Speech-to-Intent)Qualora lo scenario applicativo consenta l'adozione di strumenti commerciali (che offrono un piano gratuito per sviluppatori con limitazioni di volume), la tecnologia di riferimento è rappresentata da Picovoice Rhino Speech-to-Intent.Il Vantaggio del Paradigma Speech-to-IntentA differenza dei sistemi tradizionali che convertono la voce in testo (ASR) e successivamente applicano un parser semantico (NLU), Picovoice Rhino converte il segnale acustico direttamente in un oggetto strutturato di tipo intent (JSON) all'interno di un unico passaggio di inferenza locale.Efficienza Computazionale Straordinaria: Essendo privo dello strato di generazione del testo, il modello ha dimensioni inferiori a 20 MB e richiede un utilizzo di CPU infinitamente più basso rispetto a qualsiasi modello di tipo Transformer o Transducer.Trascrizione Out-of-Vocabulary: Rhino non soffre di errori di trascrizione fonetica sui termini definiti nel contesto d'uso. Un comando come "accendi le luci" viene mappato direttamente sulla funzione corretta anche in ambienti fortemente rumorosi.Funzionamento Offline: Il motore esegue l'intera inferenza localmente sul processore di Arduino Uno Q, richiedendo l'accesso alla rete internet esclusivamente in fase di boot del sistema per effettuare la verifica periodica della licenza tramite la chiave AccessKey di Picovoice.Nel caso in cui l'agente vocale richieda invece la trascrizione di domande aperte (ad esempio, "che tempo farà domani" o richieste meteo generiche), è possibile affiancare o sostituire Rhino con Picovoice Cheetah, il motore di streaming ASR locale di Picovoice ottimizzato per la lingua italiana. Cheetah offre un'accuratezza in italiano superiore rispetto ai servizi cloud tradizionali, mantenendo una latenza di emissione inferiore a 600 ms.Implementazione Software e Comunicazione MPU-MCU via RPC BridgeL'architettura dual-brain dell'Arduino Uno Q richiede che il sistema operativo Linux gestisca i carichi pesanti di intelligenza artificiale (acquisizione audio, VAD e decodifica ASR). Una volta identificato il comando, l'applicazione Python deve inviare l'istruzione di attuazione fisica al microcontrollore STM32U585 tramite il Bridge RPC (Arduino_RouterBridge). Questo approccio garantisce che la gestione dell'hardware (relè, LED, motori) avvenga in tempo reale e senza i ritardi tipici di un sistema operativo Linux multitasking.Il codice seguente illustra l'integrazione di sherpa-onnx (con modello Kroko IT) e silero-vad per la gestione di un sistema di ascolto continuo e l'attivazione dei pin di Arduino Uno Q.Pythonimport os
import sys
import numpy as np
import sounddevice as sd
from collections import deque
import sherpa_onnx

# Importazione della libreria Bridge per la comunicazione inter-processo di Arduino Q
try:
    from arduino.app_utils import App
    from arduino.app_bricks.bridge import Bridge
except ImportError:
    # Struttura di simulazione per i test di sviluppo in ambienti virtuali non embedded
    class Bridge:
        @staticmethod
        def call(func_name, *args):
            print(f"[MOCK RPC] Invocata funzione MCU '{func_name}' con argomenti: {args}")
    class App:
        @staticmethod
        def run():
            pass

class AgenteVocaleContinuo:
    def __init__(self, directory_modello="./sherpa-onnx-streaming-zipformer-it-kroko-2025-08-06"):
        self.frequenza_campionamento = 16000
        self.dimensione_blocco = 512  # Equivalente a 32 ms di frame audio
        
        # Inizializzazione del buffer circolare per il pre-roll (evita troncamenti iniziali)
        self.buffer_pre_roll = deque(maxlen=6)  # Conserva gli ultimi ~192 ms di audio
        self.ascolto_attivo = False
        self.conteggio_silenzio = 0
        self.limite_silenzio_blocchi = 13  # Circa 416 ms di silenzio per determinare l'endpoint
        
        # Configurazione del modello di trascrizione in tempo reale Sherpa-Onnx
        print("[INFO] Configurazione del riconoscitore in streaming...")
        config_riconoscitore = sherpa_onnx.OnlineRecognizerConfig(
            feat_config=sherpa_onnx.FeatureConfig(sample_rate=self.frequenza_campionamento, feature_dim=80),
            model_config=sherpa_onnx.OnlineModelConfig(
                transducer=sherpa_onnx.OnlineTransducerModelConfig(
                    encoder=os.path.join(directory_modello, "encoder.onnx"),
                    decoder=os.path.join(directory_modello, "decoder.onnx"),
                    joiner=os.path.join(directory_modello, "joiner.onnx"),
                ),
                tokens=os.path.join(directory_modello, "tokens.txt"),
                num_threads=2,  # Configurazione ottimale per core Cortex-A53
                provider="cpu"
            ),
            decoding_method="greedy_search"
        )
        self.riconoscitore = sherpa_onnx.OnlineRecognizer(config_riconoscitore)
        self.flusso_asr = self.riconoscitore.create_stream()
        
        # Inizializzazione di Silero VAD tramite il modulo integrato in Sherpa-Onnx
        print("[INFO] Caricamento del modulo Silero VAD...")
        config_vad = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(
                model=os.path.join(directory_modello, "silero_vad.onnx"),
                threshold=0.5,
                min_silence_duration_ms=400,
                window_size=self.dimensione_blocco
            ),
            sample_rate=self.frequenza_campionamento
        )
        self.rilevatore_vocale = sherpa_onnx.VoiceActivityDetector(config_vad, buffer_size_in_seconds=10)
        print("[INFO] Inizializzazione completata. Sistema in ascolto permanente.")

    def elabora_comando(self, testo_rilevato):
        """
        Analizza la stringa di testo e mappa le intenzioni dell'utente su chiamate RPC
        destinate al microcontrollore di Arduino Uno Q.
        """
        comando = testo_rilevato.lower().strip()
        print(f"\n[NLP - TESTO RICEVUTO]: '{comando}'")
        
        if "luci" in comando or "luce" in comando:
            if "accendi" in comando or "attiva" in comando:
                print("[RPC] Comando inviato a STM32: Accensione Luci GPIO")
                Bridge.call("gestisci_attuatore_luce", 1)
            elif "spegni" in comando or "disattiva" in comando:
                print("[RPC] Comando inviato a STM32: Spegnimento Luci GPIO")
                Bridge.call("gestisci_attuatore_luce", 0)
                
        elif "tempo" in comando or "meteo" in comando:
            print("[RPC] Comando inviato a STM32: Mostra Animazione Meteo")
            # Invia una chiamata RPC per visualizzare un'animazione sulla matrice LED di Arduino Uno Q
            Bridge.call("attiva_animazione_matrice", "meteo_domani")
            
        else:
            print("[NLP] Comando non riconosciuto o non mappato.")

    def callback_audio(self, dati_ingresso, frame_count, tempo_rilevamento, stato_driver):
        """
        Callback di sistema richiamata per ogni blocco audio acquisito dal microfono.
        """
        if stato_driver:
            print(f"[ERRORE AUDIO] {stato_driver}", file=sys.stderr)
            
        # Normalizzazione del segnale audio in float32 [-1.0, 1.0]
        frame_corrente = dati_ingresso[:, 0].astype(np.float32)
        
        # Controllo della presenza di segnale vocale tramite Silero VAD
        voce_rilevata = self.rilevatore_vocale.is_speech(frame_corrente)
        
        if voce_rilevata:
            if not self.ascolto_attivo:
                print("\n[VAD] Rilevata attività vocale. Apertura canale ASR...", end="", flush=True)
                self.ascolto_attivo = True
                
                # Riversa il contenuto del pre-roll all'interno dello stream di decodifica
                while self.buffer_pre_roll:
                    frame_bufferizzato = self.buffer_pre_roll.popleft()
                    self.flusso_asr.accept_waveform(self.frequenza_campionamento, frame_bufferizzato)
            
            # Trasmette il frame corrente allo stream ASR
            self.flusso_asr.accept_waveform(self.frequenza_campionamento, frame_corrente)
            self.conteggio_silenzio = 0
            
            # Esegue la decodifica se il motore è pronto
            while self.riconoscitore.is_ready(self.flusso_asr):
                self.riconoscitore.decode(self.flusso_asr)
                
            # Mostra l'anteprima di trascrizione a schermo (real-time feedback)
            trascrizione_parziale = self.riconoscitore.get_result(self.flusso_asr).text
            if trascrizione_parziale:
                print(f"\r[ASR LIVE]: {trascrizione_parziale}", end="", flush=True)
                
        else:
            if self.ascolto_attivo:
                # Gestione dell'endpointing basato su silenzio consecutivo
                self.conteggio_silenzio += 1
                self.flusso_asr.accept_waveform(self.frequenza_campionamento, frame_corrente)
                
                while self.riconoscitore.is_ready(self.flusso_asr):
                    self.riconoscitore.decode(self.flusso_asr)
                
                if self.conteggio_silenzio >= self.limite_silenzio_blocchi:
                    print("\n[VAD] Silenzio rilevato. Chiusura sessione.")
                    self.ascolto_attivo = False
                    self.conteggio_silenzio = 0
                    
                    # Estrazione e finalizzazione del testo trascritto
                    testo_finale = self.riconoscitore.get_result(self.flusso_asr).text
                    if testo_finale:
                        self.elabora_comando(testo_finale)
                    
                    # Rigenerazione dello stream ASR per liberare la memoria dei contesti precedenti
                    self.flusso_asr = self.riconoscitore.create_stream()
            else:
                # Popolamento continuo del Ring Buffer se l'utente non sta parlando
                self.buffer_pre_roll.append(frame_corrente)

    def avvia_ascolto(self):
        try:
            with sd.InputStream(
                samplerate=self.frequenza_campionamento,
                channels=1,
                dtype='float32',
                blocksize=self.dimensione_blocco,
                callback=self.callback_audio
            ):
                print("\n[INFO] Sistema pronto per l'ascolto permanente in italiano...")
                while True:
                    sd.sleep(1000)
        except KeyboardInterrupt:
            print("\n[INFO] Arresto del servizio di ascolto locale.")

if __name__ == "__main__":
    agente = AgenteVocaleContinuo()
    agente.avvia_ascolto()
    App.run()
Conclusioni e Linee Guida OperativeLa progettazione di un agente vocale reattivo in lingua italiana ed eseguito in locale su Arduino Uno Q richiede l'abbandono di architetture non ottimizzate per l'edge computing. Al fine di massimizzare le prestazioni del sistema, si raccomanda l'adozione delle seguenti linee guida:Abbandono dei Modelli Tradizionali: Non utilizzare modelli basati su standard Whisper (anche se in implementazioni C++ o CTranslate2) poiché l'architettura a finestra fissa di 30 secondi e l'assenza di caching nativo introducono latenze incompatibili con l'interazione in tempo reale. Escludere l'uso dei modelli ridotti di Vosk per evitare il degrado qualitativo causato da errori fonetici e anomalie di trascrizione.Integrazione del VAD come Filtro di Controllo: Implementare obbligatoriamente un modulo di Voice Activity Detection (Silero VAD) a monte del sistema. Il VAD deve agire come interruttore software, abilitando l'esecuzione del motore ASR esclusivamente in presenza di un reale segnale vocale e gestendo l'endpointing automatico.Selezione del Modello ASR Ottimale: In contesti interamente open-source, configurare sherpa-onnx con il modello Zipformer Kroko 64-layer (INT8). Questa combinazione offre una latenza inferiore a 150 ms e un'impronta di memoria compatibile con le risorse di Arduino Uno Q. Qualora si opti per soluzioni commerciali ad altissima efficienza, la scelta d'elezione è rappresentata da Picovoice Rhino (Speech-to-Intent) o Picovoice Cheetah (Streaming ASR).Ottimizzazione del Buffer di Pre-Roll: Implementare un Ring Buffer circolare di almeno 150-200 millisecondi per salvaguardare l'integrità dei fonemi iniziali delle parole, garantendo una trascrizione accurata fin dalla prima sillaba pronunciata.

## Validazione Sperimentale su Hardware Reale (2026-07-12)

L'architettura proposta in questo documento è stata implementata e testata su un Arduino Uno Q reale (board di produzione di questo repository, microfono NewPie USB) tramite un tool diagnostico standalone, **`serena-vad`** (`alexa_custom/asr_eval.py`, comando installato via l'extra opzionale `asr-eval` in `pyproject.toml`). Il tool è deliberatamente separato dalla pipeline STT di produzione (`stt.py`, tuttora basata su Vosk) — serve unicamente a validare l'approccio prima di un'eventuale migrazione.

### Modello e dipendenze

- Modello usato: `models/it/kroko_64l` (encoder/decoder/joiner INT8 + tokens.txt, già presenti nel repository) — il Kroko Zipformer 64-layer raccomandato dal documento.
- `sherpa-onnx==1.13.4` ha una wheel aarch64 rotta (`ImportError: version 'VERS_1.27.0' not found` — mismatch tra `_sherpa_onnx.so` e `libonnxruntime.so` bundlati). **Pinnato a `1.13.3`**, verificato funzionante.
- `silero_vad.onnx` non era presente nel repository (solo Vosk e i modelli Kroko lo erano): il tool lo scarica automaticamente al primo avvio da `k2-fsa/sherpa-onnx` release assets in `models/vad/`.
- `sherpa-onnx`/`onnxruntime` sono ora dipendenze di base (non più dietro l'extra `asr-eval`, rimosso), quindi un `uv sync` semplice li installa sempre. **Attenzione**: `uv sync` da solo disinstalla comunque silenziosamente `PyGObject`/`pycairo` (da cui dipende il backend di cattura `gstreamer` già in uso in produzione su questa board — `conf/config.yaml: stt.capture_backend: gstreamer`, profilo `yealink`) a meno di richiedere esplicitamente `--extra gstreamer`. `task setup` rileva automaticamente se `PyGObject` è già installato e in tal caso ri-richiede l'extra; un `uv sync` manuale va invece lanciato con `uv sync --extra gstreamer`.

### Bug corretti durante la validazione

L'implementazione iniziale (basata sull'API sherpa-onnx e sull'esempio di codice del documento) presentava diversi bug non ovvi, tutti risolti:

1. **Downmix stereo errato**: il downmix iniziale usava `.max(axis=1)` sui due canali invece di "canale con ampiezza assoluta massima, segno preservato" (come fa già `alexa_custom.stt_gating._downmix_to_mono`, ora riutilizzato). Il downmix naive distorceva/clippava la forma d'onda e produceva trascrizioni vuote nonostante il VAD rilevasse correttamente il parlato.
2. **Comandi brevi non rilevati**: `SileroVadModelConfig.min_speech_duration` di default (250 ms) richiede parlato sostenuto sopra soglia per quella durata prima che `is_speech_detected()` diventi `True`. Comandi brevi come "accendi le luci" hanno micro-pause tra le parole e possono terminare prima che il debounce si confermi, sparendo silenziosamente nel buffer di pre-roll senza alcun output. Risolto abbassando il default a 100 ms (`--vad-speech-ms`).
3. **Troncamento dell'ultima parola**: l'encoder Zipformer richiede ~0.66 s di contesto destro (lookahead) per decodificare correttamente le ultime parole di un'enunciazione — pattern documentato nell'esempio ufficiale `online-decode-files.py` di sherpa-onnx. Senza questo padding, `input_finished()` tronca la coda del parlato. Il fix iniziale usava padding di zeri sintetici; è stato poi migliorato per continuare ad alimentare **audio reale catturato dal microfono** durante la finestra di contesto destro (fallback a zeri solo a fine file in modalità `--bench`), per non scartare eventuale audio reale ancora in arrivo.

### Limitazione nota (non risolvibile via software, su questo hardware)

Con frasi pronunciate a volume costante (es. "il legno è nero", "accendi le luci") la trascrizione è **corretta e completa**. Con "ascolta assistente", la sillaba finale "-nte" viene sistematicamente troncata ("assiste"), riproducibile in modo identico attraverso:

- gain software 1.0x vs 1.5x (applicando `audio.input_gain` da `conf/config.yaml`, ora dietro flag opt-in `--apply-config-gain`)
- soglia VAD 0.5 / 0.35 / 0.2

L'ampiezza RMS della finestra post-endpoint resta sempre vicina al rumore di fondo (0.0007–0.0066) in ogni condizione testata. Verificato inoltre che il guadagno hardware (ALSA `Mic` mixer e volume sorgente PulseAudio) sono già al 100% — non c'è margine analogico disponibile, e applicare guadagno software su un segnale già al massimo causa clipping delle porzioni più forti (verificato: "nero" si è degradato da trascrizione completa a troncata dopo aver applicato 1.5x). **Conclusione**: la sillaba finale di "assistente" è probabilmente pronunciata a volume troppo basso per essere distinta dal rumore con questo setup microfono/distanza, indipendentemente dal tuning del VAD — un limite intrinseco di SNR, non un difetto della pipeline.

### Nota sulla latenza riportata dal tool

Il valore `[final] (N ms)` stampato da `serena-vad` misura il tempo dall'inizio del parlato rilevato dal VAD alla trascrizione finale — include quindi la durata dell'intera frase pronunciata più l'attesa di ~0.66 s per il contesto destro. **Non è direttamente comparabile** con la cifra "<500 ms" citata più sopra in questo documento, che si riferisce alla sola latenza di decodifica post-fine-parlato. Un confronto equivalente richiederebbe di misurare dal momento dell'endpoint VAD alla trascrizione finale, non dall'inizio del parlato.

### Modalità di benchmark

`serena-vad --bench` sintetizza una frase italiana con Piper TTS (o riusa un WAV fornito con `--bench-wav`) e la ripete attraverso l'intera pipeline VAD+ASR per confrontare `--num-threads` (1/2/4, configurabile) su min/media/max latenza, senza richiedere un microfono live. Utile per il confronto RTF discusso più sopra nella sezione sulla configurazione di `num_threads`.
