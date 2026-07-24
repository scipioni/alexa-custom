"""ONVIF Events — automatic subnet scan, ONVIF/Dahua event ingestion, JSON
persistence, MQTT/Home-Assistant publishing, and a web dashboard.

Package split of the former monolithic ``app.py``. The refactor is behaviour-
preserving: MQTT topics/payloads and every HTTP route response are unchanged.

Module layers (imports flow one direction):
  config, state  →  connect, mqtt  →  scan, worker  →  web
"""
