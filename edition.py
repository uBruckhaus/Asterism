"""How much of a harness's sessions this edition may show.

    NUMBERS  counts, times, tokens, lines changed, cost (harnesses.py and its adapters)
    TITLES   the titles a harness gave its sessions itself (session_topics.py)
    SUMMARY  titles and numbers sent to the user's own Claude Code on a click (session_topics.py)

The level is the highest of: NUMBERS; the privacy level of the add-ons loaded now (addons.py,
Asterism only; the AI Agents Map plugin has no add-on loader); and, until it becomes an add-on,
session_topics.py where it ships (Asterism; tools/vendor-into-plugin.sh leaves it out of the
plugin). So the plugin can show numbers only: the code that reads titles is not in it at all.
"""

NUMBERS, TITLES, SUMMARY = 1, 2, 3

_built_in = None


def _built_in_level() -> int:
    global _built_in
    if _built_in is None:
        try:
            import session_topics  # noqa: F401
            _built_in = SUMMARY
        except ImportError:
            _built_in = NUMBERS
    return _built_in


def maximum() -> int:
    try:
        import addon_api
        loaded = addon_api.loaded_privacy()
    except ImportError:                 # the AI Agents Map plugin: no add-ons
        loaded = 0
    return max(NUMBERS, _built_in_level(), loaded)


def allows(level: int) -> bool:
    return level <= maximum()
