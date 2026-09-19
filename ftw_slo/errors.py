"""Error types with file / key-path context for clear messages."""


class SpecError(Exception):
    """A problem in an SLO spec. `path` is a dotted key path such as slos[0].objective."""

    def __init__(self, source, path, message):
        super().__init__(message)
        self.source = source
        self.path = path
        self.message = message

    def __str__(self):
        where = self.source or "<input>"
        if self.path:
            where += f": {self.path}"
        return f"{where}: {self.message}"


class SpecErrors(Exception):
    """Several SpecError at once (validation collects all problems before failing)."""

    def __init__(self, errors):
        super().__init__("\n".join(str(e) for e in errors))
        self.errors = list(errors)


class EditionError(Exception):
    """A feature that is not part of this edition (Starter / Pro / Studio)."""
