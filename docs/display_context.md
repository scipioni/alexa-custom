# Display Feedback — Contesto per nuova chat

## Stato attuale

Tutto il codice Python è scritto e funziona su PC. Sull'UNO Q il BridgeDisplay si connette ma il driver kernel `qcom_geni_serial` blocca `/dev/ttyHS1` (la UART tra MPU e STM32).

## File implementati

### `alexa_custom/display.py`
- `DisplayBackend` (ABC) — `show(state)`, `clear()`
- `MockDisplay` — logger + ASCII art, per PC
- `GpioLedDisplay` — `/sys/class/leds/` (LED MPU, funziona subito)
- `BridgeDisplay` — comunica col firmware STM32 via seriale MsgPack RPC
- `_BridgeClient` — client MsgPack RPC su `/dev/ttyMSM0`
- `get_display_backend()` — factory auto-selection: bridge → gpio → mock
- `DisplayController` — thread + coda eventi, si aggancia al flusso eventi del web server

### `alexa_custom/config.py`
- `DisplayConfig` dataclass: `enabled`, `backend`, `matrix_brightness`, `led_brightness`
- Campo `display` in `ActionsConfig`, parser in `_parse_actions_config()`

### `alexa_custom/web.py`
- `extra_event_cb`, `extra_stt_event_cb` in WebServer e run_web()
- Chaining callbacks in run()

### `alexa_custom/client.py`
- Creazione `DisplayController` in `main()` quando config.display.enabled
- Passaggio callback a `run_web()`

### `setup/display_firmware/display_firmware.ino`
Firmware per STM32U585. Standalone RPCServer su Serial1 (nessun Router).
- 9 icone 8×13 (byte array row-major, 104 byte ciascuna)
- RPC: ping, set_matrix_icon, set_leds, clear
- Non usa `ArduinoRouterBridge` — solo `Arduino_RPClite` diretto
- **Flashato con successo sulla UNO Q**

### `setup/display_firmware/uart_bridge.c`
Minimal C bridge per bypassare il driver kernel. Usa `/dev/mem` per accedere direttamente ai registri UART.
- Mappa UART a 0x4a88000
- TX FIFO a 0x700, RX FIFO a 0x780
- Legge stdin → TX FIFO, RX FIFO → stdout
- **Non ancora compilato/testato sulla UNO Q**

### `tests/test_display.py`
27 test per backend, factory, controller, configurazione.

### `docs/display_setup.md`
Guida setup per UNO Q (parzialmente obsoleta).

## Config bloccante

```
display:
  enabled: true
  backend: auto
```

`Backend 'auto'` su UNO Q prova bridge → gpio → mock.
- BridgeDisplay apre `/dev/ttyMSM0` (che NON è collegato allo STM32) → RPC timeout
- GpioLedDisplay funziona ma solo 2 LED MPU
- La vera UART STM32 è su `/dev/ttyHS1` ma il driver `qcom_geni_serial` la blocca (EBUSY)

## Operazioni da fare sulla UNO Q

### 1. Compilare e installare uart_bridge
```bash
cd /home/arduino/alexa-custom && git pull
gcc -o uart_bridge setup/display_firmware/uart_bridge.c
sudo timeout 3 ./uart_bridge
```
Dovrebbe stampare `tx_st=0x... rx_st=0x...`. Se stampa, la UART è accessibile.

### 2. Test comunicazione STM32
```bash
# In un terminale:
sudo ./uart_bridge

# In un altro terminale (o dopo aver avviato):
printf '\x94\x00\x00\xa4ping\x90' | sudo ./uart_bridge | xxd
```
Se l'STM32 risponde, si vedrà la risposta MsgPack.

### 3. Aggiornare display.py per usare uart_bridge
Sostituire `_BridgeClient` per chiamare `sudo ./uart_bridge` come subprocess invece di pyserial su ttyMSM0.

### 4. Test finale
```bash
serena-client
```
La matrice 8×13 dovrebbe mostrare ◎ (idle), poi cambiare con gli eventi.

## Alternative se uart_bridge non funziona

### A. Kernel module UIO
Scrivere un modulo kernel minimale che espone i registri UART via UIO framework. Non serve se uart_bridge funziona.

### B. Modifica firmware STM32
Riuscire a far comunicare STM32 su altra UART collegata a ttyMSM0 (già provato Serial2, non funzionato).
