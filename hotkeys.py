"""Portable hotkey spec parsing and validation shared by runtime and dashboard."""

MODIFIERS = {"alt", "alt_r", "cmd", "cmd_r", "ctrl", "ctrl_r", "shift", "shift_r"}
NAMED_KEYS = {
    "space", "enter", "tab", "esc", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "page_up", "page_down",
}
NAMED_KEYS.update({f"f{number}" for number in range(1, 21)})


def normalize_hotkey(spec):
    """Return a stable plus-separated hotkey spec or raise ValueError."""
    parts = [str(part).strip().lower() for part in str(spec or "").split("+")]
    if not parts or any(not part for part in parts):
        raise ValueError("단축키를 입력해 주세요.")
    if len(set(parts)) != len(parts):
        raise ValueError("같은 키를 두 번 넣을 수 없습니다.")
    for part in parts:
        if part in MODIFIERS or part in NAMED_KEYS:
            continue
        if len(part) == 1 and part.isprintable() and part != "+":
            continue
        raise ValueError(f"지원하지 않는 키입니다: {part}")
    modifiers = sorted((part for part in parts if part in MODIFIERS), key=_modifier_order)
    regular = [part for part in parts if part not in MODIFIERS]
    if len(regular) > 1:
        raise ValueError("문자나 기능키는 하나만 지정할 수 있습니다.")
    return "+".join(modifiers + regular)


def hotkey_parts(spec):
    return frozenset(normalize_hotkey(spec).split("+"))


def validate_hotkey_pair(hold_key, toggle_key):
    try:
        hold = normalize_hotkey(hold_key)
        toggle = normalize_hotkey(toggle_key)
    except ValueError as exc:
        return False, str(exc)
    if hold == toggle:
        return False, "꾹 누르기와 토글 단축키는 서로 달라야 합니다."
    return True, ""


def _modifier_order(token):
    base = token.removesuffix("_r")
    return ("ctrl", "alt", "shift", "cmd").index(base), token.endswith("_r")
