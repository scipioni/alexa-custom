"""collect_prompt_texts: gather static ask/say prompts for TTS pre-warming."""

from alexa_custom.actions import collect_prompt_texts
from alexa_custom.config import ActionEntry, ActionsConfig, Trigger


def _cfg(triggers, on_startup=None) -> ActionsConfig:
    return ActionsConfig(wake_words=[], triggers=triggers, on_startup=on_startup or [])


class TestCollectPromptTexts:
    def test_gathers_ask_and_say_including_nested_reply_and_else(self):
        ask = ActionEntry(
            type="ask",
            params={"text": "Vuoi chiamare assistenza ?"},
            on_reply=[
                Trigger(
                    commands=["si"],
                    actions=[ActionEntry(type="say", params={"text": "Sto chiamando"})],
                )
            ],
            on_else=[ActionEntry(type="say", params={"text": "Non ho capito"})],
        )
        texts = collect_prompt_texts(
            _cfg([Trigger(commands=["chiama"], actions=[ask])])
        )
        assert texts == ["Vuoi chiamare assistenza ?", "Sto chiamando", "Non ho capito"]

    def test_includes_on_startup_and_dedups_preserving_order(self):
        say = ActionEntry(type="say", params={"text": "Sistema pronto"})
        dup = ActionEntry(type="say", params={"text": "Sistema pronto"})
        cfg = _cfg([Trigger(commands=["x"], actions=[dup])], on_startup=[say])
        # on_startup visited after triggers; the duplicate is dropped.
        assert collect_prompt_texts(cfg) == ["Sistema pronto"]

    def test_skips_dynamic_shell_templates(self):
        actions = [
            ActionEntry(type="say", params={"text": "$(date +%H:%M)"}),
            ActionEntry(type="say", params={"text": "${VAR}"}),
            ActionEntry(type="say", params={"text": "`cmd`"}),
            ActionEntry(type="say", params={"text": "Buongiorno"}),
        ]
        assert collect_prompt_texts(
            _cfg([Trigger(commands=["x"], actions=actions)])
        ) == ["Buongiorno"]

    def test_ignores_non_tts_actions_and_empty_text(self):
        actions = [
            ActionEntry(type="livekit_join", params={}),
            ActionEntry(type="say", params={"text": "   "}),  # blank
            ActionEntry(type="say", params={}),  # no text
            ActionEntry(type="say", params={"text": "Ok"}),
        ]
        assert collect_prompt_texts(
            _cfg([Trigger(commands=["x"], actions=actions)])
        ) == ["Ok"]
