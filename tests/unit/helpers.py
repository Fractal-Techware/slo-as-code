"""Shared helpers for the ftw-slo unit tests. Run from the kit folder:

    python3 -m pytest tests/unit          (or)          python3 -m unittest discover -s tests/unit
"""
import io
import os
import sys
import tempfile
import textwrap
from contextlib import redirect_stderr, redirect_stdout

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if KIT not in sys.path:
    sys.path.insert(0, KIT)

from ftw_slo import cli, edition  # noqa: E402

EXAMPLES = os.path.join(KIT, "examples")
GENERATED = os.path.join(KIT, "generated")
PROMTOOL = os.path.join(KIT, "tests", "promtool")


def write_spec(tmpdir, text, name="spec.yaml"):
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text).lstrip())
    return path


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def tree(base):
    files = {}
    for dirpath, _, filenames in os.walk(base):
        for f in filenames:
            p = os.path.join(dirpath, f)
            with open(p, "rb") as fh:
                files[os.path.relpath(p, base)] = fh.read()
    return files


def default_only():
    return {"free": "rules", "starter": "rules", "pro": "rules,crd,dashboards", "studio": "rules,crd,dashboards,helm"}[edition.EDITION]


class TempDir:
    def __enter__(self):
        self._t = tempfile.TemporaryDirectory(prefix="ftwslo-test-")
        return self._t.name

    def __exit__(self, *exc):
        self._t.cleanup()


MINIMAL = """
apiVersion: ftw-slo/v1
service: checkout
slos:
  - name: availability
    objective: 99.9
    sli:
      template: http-availability
      params:
        selector: 'job="checkout"'
"""
