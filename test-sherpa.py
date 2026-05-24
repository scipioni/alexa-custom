import os
import sys
import queue
import sounddevice as sd
import sherpa_onnx

"""
download model:

hf download hudaiapa88/sherpa-stt-onnx \
  --local-dir ./models \
  --include "it/kroko_128l/*"
"""


def run_live_microphone():
    # 1. Define paths to your downloaded kroko_128l assets
    model_dir = "./models/it/kroko_128l"

    encoder = os.path.join(model_dir, "encoder.int8.onnx")
    decoder = os.path.join(model_dir, "decoder.int8.onnx")
    joiner = os.path.join(model_dir, "joiner.int8.onnx")
    tokens = os.path.join(model_dir, "tokens.txt")

    # Quick sanity check
    for path in [encoder, decoder, joiner, tokens]:
        if not os.path.exists(path):
            print(f"Error: Missing file -> {path}")
            sys.exit(1)

    # 2. Initialize the Online Recognizer
    print("Inizializzazione del modello Kroko in corso...")
    recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=tokens,
        encoder=encoder,
        decoder=decoder,
        joiner=joiner,
        num_threads=4,  # Good thread count for real-time responsiveness
        decoding_method="greedy_search",
        sample_rate=16000,
        feature_dim=80,
        provider="cpu",
    )

    # 3. Thread-safe queue to pass audio from the mic callback to the main thread
    audio_queue = queue.Queue()

    def audio_callback(indata, frames, time, status):
        """This callback is invoked for each audio block by sounddevice."""
        if status:
            print(status, file=sys.stderr)
        audio_queue.put(indata.copy())

    # 4. Open the mic input stream
    sample_rate = 16000
    block_size = int(sample_rate * 0.1)  # 100ms chunks

    stream = recognizer.create_stream()

    print("\n--- Modello pronto! Inizia a parlare in Italiano ---")
    print("Premi Ctrl+C per interrompere.\n")

    try:
        with sd.InputStream(
            channels=1,
            samplerate=sample_rate,
            blocksize=block_size,
            dtype="float32",
            callback=audio_callback,
        ):
            last_text = ""

            while True:
                # Get the next chunk of audio from the queue
                samples = audio_queue.get()
                samples = samples.flatten()

                # Feed audio to the model using the correct keyword: waveform=
                stream.accept_waveform(sample_rate=sample_rate, waveform=samples)

                # Decode chunks as they become ready
                while recognizer.is_ready(stream):
                    recognizer.decode_stream(stream)

                # Output the ongoing results dynamically
                # Fixed: treating result directly as a string or fallback to string casting
                result = recognizer.get_result(stream)
                text = (
                    result.strip() if isinstance(result, str) else result.text.strip()
                )

                if text and text != last_text:
                    print(f"\rTrascrizione: {text}", end="", flush=True)
                    last_text = text

                # Optional: Handle endpointing to clear the terminal line on pauses
                if recognizer.is_endpoint(stream):
                    if text:
                        print(f"\rFrase finale: {text}")
                    recognizer.reset(stream)
                    last_text = ""

    except KeyboardInterrupt:
        print("\n\nSessione terminata dall'utente.")
    except Exception as e:
        print(f"\nErrore durante l'esecuzione: {e}")


if __name__ == "__main__":
    run_live_microphone()
