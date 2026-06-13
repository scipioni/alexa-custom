## ADDED Requirements

### Requirement: Bounded dispatch execution
A dispatched turn executed on the STT thread's event loop SHALL be subject to a configurable time ceiling (`recognition.dispatch_timeout`, in seconds, with a backward-compatible default). When a dispatch exceeds the ceiling, the system SHALL abort that turn, log the timeout, reset the in-loop recognition state so the next utterance is processed cleanly, and resume listening. The STT thread SHALL NOT remain blocked on a single turn beyond the ceiling. A turn that completes within the ceiling SHALL behave exactly as before.

#### Scenario: Dispatch completes within the ceiling
- **WHEN** a dispatched turn finishes before `recognition.dispatch_timeout` elapses
- **THEN** all actions execute normally and recognition resumes with no timeout logged

#### Scenario: Dispatch exceeds the ceiling
- **WHEN** a dispatched turn (e.g. a wedged `listen_fn` or stalled LiveKit connect) runs longer than `recognition.dispatch_timeout`
- **THEN** the turn is aborted, a timeout is logged, recognition state is reset, and the STT thread resumes listening for the next wake word

#### Scenario: Default ceiling when unconfigured
- **WHEN** `recognition.dispatch_timeout` is absent from config
- **THEN** a conservative default ceiling applies and existing trigger flows are unaffected
