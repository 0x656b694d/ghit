import sys


class _Verbosity:
    on = False


def set_verbose(on: bool) -> None:
    _Verbosity.on = on


def verbose(*args, **kwargs):
    """Explain to the user what is happening when --verbose is set."""
    if _Verbosity.on:
        print(*args, **kwargs)  # noqa: T201


def stdout(*args, **kwargs):
    print(*args, **kwargs)  # noqa: T201


def stderr(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)  # noqa: T201
