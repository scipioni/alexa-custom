import os
import queue
import sys
import json
import sounddevice as sd
from vosk import Model, KaldiRecognizer

# Queue to stream audio chunks
q = queue.Queue()

def callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

# Point to your newly downloaded Italian model folder
if not os.path.exists("model-it"):
    print("Errore: La cartella 'model-it' non esiste.")
    sys.exit(1)

model = Model("model-it")
recognizer = KaldiRecognizer(model, 16000)

# Optional: Limit vocabulary to just your target commands to boost accuracy
# recognizer.SetWords(True) 

print("Vosk pronto. Parla adesso...")

# Start the audio stream (Make sure your USB Mic is connected)
with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype='int16',
                        channels=1, callback=callback):
    
    while True:
        data = q.get()
        if recognizer.AcceptWaveform(data):
            # Parse the JSON string result
            result_json = json.loads(recognizer.Result())
            text = result_json.get("text", "")
            
            if text:
                print(f"Riconosciuto: {text}")
                
                # Simple Italian keyword triggering logic
                if "accendi" in text:
                    print("--> Trigger: Accensione in corso...")
                    # TODO: Trigger RPC call to STM32 to turn on a digital pin
                elif "spegni" in text:
                    print("--> Trigger: Spegnimento in corso...")
                    # TODO: Trigger RPC call to STM32 to turn off a digital pin
