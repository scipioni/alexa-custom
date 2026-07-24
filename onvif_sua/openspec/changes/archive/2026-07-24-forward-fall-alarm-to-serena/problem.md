# Problem: no delivery assurance on the sole call-for-help path

## Summary

The Serena fall bridge forwards a fall-start as a **fire-and-forget** MQTT command
(`<prefix>/<node_id>/trigger/run`, non-retained, QoS 1). The operator has decided
this Serena voice-confirmation is the **sole** call-for-help responder (no Home
Assistant automation on the retained state topic as a backstop). That combination —
a single, unconfirmed channel for a life-safety ("person down") event — is the core
problem this change must manage.

ONVIF_SUA can confirm delivery **to the broker**, but it **cannot confirm that Serena
received or acted on the command**. True end-to-end confirmation would require Serena
to publish an ack/echo, which violates this change's zero-Serena-code goal (held firm
by decision). So a residual blind spot is structural, not an oversight.

## Silent-failure modes

Grounded in the code (`onvif_sua/mqtt.py`, `serena/alexa_custom/mqtt.py`):

| Failure mode | What happens | Detectable on ONVIF side? |
|---|---|---|
| **Wrong / typo `node_id`** | Broker accepts the publish to a topic nobody subscribes to. Serena defaults `node_id` to `socket.gethostname()` (`alexa_custom/mqtt.py:26`), so guessing `serena` silently misses. | ❌ Not at runtime — only at commissioning (A) or via the diagnostic showing the resolved topic (D). |
| **Broker down at fall time** | `_mqtt_client` is *not* `None` (created via `connect_async` + `loop_start`, `mqtt.py:84-86`), but `.is_connected()` is false; the QoS-1 message is buffered or dropped. | ⚠️ Only if we check `is_connected()` / publish rc (B). |
| **Serena crashed / not subscribed / phrase no-match** | Message reaches the broker fine; Serena never acts. Serena has **no LWT/`will_set`** and its `offline` state is non-retained (`alexa_custom/mqtt.py:52,199`), so its liveness is not reliably observable either. | ❌ Never — requires a Serena-side ack (out of scope). |

## Constraints that shape the solution

- **Zero Serena code** (held firm): no ack/echo, so "did Serena act?" is unverifiable.
- **Sole path** (operator's choice): no independent HA net, so the bridge's own
  visibility carries all the assurance weight.
- **Fault isolation**: the emit sits inline in the detection read loop
  (`worker.py:521`), wrapped by the catch-all at `worker.py:563` that waits 30 s and
  reconnects — so an unhandled emit exception would cause a silent non-delivery *and*
  a 30 s detection blackout. The emit must never propagate (addressed by the
  "Emit never disrupts fall detection" requirement).

## Mitigations adopted (A + B + D)

Best achievable purely on the ONVIF side — see the "Bridge observability and delivery
visibility" requirement in `specs/serena-fall-bridge/spec.md` and tasks 2.4, 2.5, 2b:

- **(A) Commissioning visibility** — log the fully-resolved `trigger/run` topic once at
  init; documented `mosquitto_sub -t 'alexa/#'` test-fall verification (task 6.1a).
  Kills the #1 real failure (node_id ≠ Serena hostname) at setup time.
- **(B) Emit-time connectivity check** — `is_connected()` before publish; log an
  **error** (not silent) if disconnected; optional `wait_for_publish()` to confirm the
  broker PUBACK. Catches broker-down-at-emit; confirms broker receipt only.
- **(D) Retained HA diagnostic entity** — continuous bridge health (enabled /
  connected / resolved topic) so a config or connection regression is visible after
  commissioning, not only during it.

## Residual risk (accepted, must stay documented)

Even with A + B + D, a **Serena crash, a phrase that silently stops matching, or an
unanswered prompt** are invisible to ONVIF, and there is no independent backstop.
For a "person down" system this is a fragile posture. The cheapest de-risking — **zero
Serena code and zero new ONVIF code** — is a passive Home Assistant automation on the
already-published retained `onvif/<cam>/alarms/fall` topic as a truly independent
notification. It was declined ("sole path") and is recorded here so the trade-off is
explicit and revisitable.
