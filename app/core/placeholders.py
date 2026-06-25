import re

ALLOWED_TOKENS = ("name", "numbers", "count", "price", "sheet_url", "event_name")

_TOKEN_RE = re.compile(r"\{(\w+)\}")


def render(template: str, ctx: dict) -> str:
    """Подставляет {token} из ctx. Неизвестные/отсутствующие токены оставляет как есть ({token}). Не падает."""
    if not template:
        return template or ""

    def _repl(m: re.Match) -> str:
        key = m.group(1)
        if key in ctx and ctx[key] is not None:
            return str(ctx[key])
        return m.group(0)  # оставить как есть

    return _TOKEN_RE.sub(_repl, template)


def format_numbers(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers)
