import time
from alexa_custom.display import get_display_backend


def main():
    print("Inizializzazione del backend del display (Bridge Zephyr)...")

    try:
        # get_display_backend("auto") rileverà la porta seriale /dev/ttyHS1 da solo
        display = get_display_backend("auto")

        print("Backend avviato! Provo a mandare gli stati sulla matrice LED...")

        while True:
            # Gli stati ("state") di solito mappano icone o animazioni specifiche nel firmware
            print("Stato: ascolto (listening)...")
            display.show("listening")
            time.sleep(4)

            print("Stato: elaborazione (thinking)...")
            display.show("thinking")
            time.sleep(4)

            print("Pulisco lo schermo...")
            display.clear()
            time.sleep(2)

    except KeyboardInterrupt:
        print("\nScript interrotto.")
        try:
            display.clear()
        except Exception:
            pass
    except Exception as e:
        print(f"Errore durante l'uso del display: {e}")


if __name__ == "__main__":
    main()
