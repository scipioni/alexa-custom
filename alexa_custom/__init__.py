"""LiveKit headless audio client for voice-activated smart assistants."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("alexa-custom")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"
