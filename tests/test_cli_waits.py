#!/usr/bin/env python3
"""Suite for daedalus_cli — what a command's wait admits and survives.

A sibling of tests/test_cli.py, which is size-frozen. Same fixture style:
the CLI is always run as a subprocess, the way a shell would run it, against
a real bridge() or against a stub front end that answers the way a proxy in
front of the bridge does.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _drain  # noqa: E402
import _util  # noqa: E402
from _cmdqueue import clear_command_queue  # noqa: E402
from _queueread import queued_command  # noqa: E402

# Keep bridge children off the fixed MCP port (see tests/_bridge.py).
os.environ.setdefault('DAEDALUS_MCP_PORT', '0')

CLI = [sys.executable, '-c', 'from daedalus_cli.cli import main; main()']

# The result header's marker is whichever glyph the console can encode, so
# what is pinned is that a marker immediately precedes the id (see
# tests/test_cli.py).
IN_MARKS = ('←', '<-')
TOK = 'clitok'
# The bridge child inherits its token from here, the way test_cli.py's does.
os.environ['TOKEN'] = ''
os.environ['DAEDALUS_TOKEN'] = TOK


def cli_env(**overrides):
    """A clean environment: none of the CLI's config vars leak in from ours."""
    env = dict(os.environ)
    for k in ('DAEDALUS_URL', 'DAEDALUS_TOKEN', 'TOKEN', 'ID',
              'PYTHONIOENCODING'):
        env.pop(k, None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env.update(overrides)
    return env


def run_cli(args, env, timeout=60):
    return subprocess.run(CLI + args, cwd=str(_util.ROOT), env=env,
                          capture_output=True, text=True, encoding='utf-8',
                          timeout=timeout)


def _answer_eval(base, docroot, argv, env, tab, result):
    """Run one eval subcommand and play the extension over HTTP.

    Returns (returncode, stdout, stderr). The answer is posted as soon as
    the command is queued, so a CLI that gives up before that is one that
    gave up before the browser could possibly have answered.
    """
    # Nothing drains this queue — there is no extension here — so an
    # earlier case's entry may remain; the entry answered must be this one.
    qdir = Path(docroot) / 'commands' / f'{TOK}_{tab}'
    survivors = clear_command_queue(qdir)
    proc = subprocess.Popen(
        CLI + argv, cwd=str(_util.ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8')
    try:
        queued = queued_command(
            qdir, 'the enqueued command file', exclude=survivors)
        status, _ = _util.post_json(base + '/result', {
            'token': TOK, 'tabId': tab, 'id': queued['id'],
            'result': result, 'error': None, 'ts': 1,
            'world': 'page:cdp', '_did': queued['_did']})
        assert status == 200, status
        out, err = proc.communicate(timeout=60)
    finally:
        _drain.kill_and_drain(proc)
    return proc.returncode, out, err


def test_a_zero_timeout_on_exec_and_put_reads_as_the_default(tmp):
    """`-t 0` waits the documented default; it does not time out at once.

    positive_timeout admits 0 on the promise that every call site reads it
    as unset, the way screenshot and cookies do. put and exec handed it
    straight to the waiter, whose deadline was now plus nothing, so the CLI
    reported `Timeout (0s)` for a command the bridge had already queued and
    the browser went on to run — and a retry ran the side effect twice.
    """
    source = Path(tmp) / 'job.js'
    source.write_text('document.title', encoding='utf-8')
    with _util.bridge(tmp) as (base, docroot):
        env = cli_env(DAEDALUS_URL=base, DAEDALUS_TOKEN=TOK, ID='tab0')
        cases = (
            ['exec', 'job0', 'document.title', '-t', '0'],
            ['put', 'job1', str(source), '--timeout', '0'],
        )
        for argv in cases:
            code, out, err = _answer_eval(
                base, docroot, argv, env, 'tab0', 'Zero Title')
            assert code == 0, (argv, code, out, err)
            assert 'Timeout' not in err, (argv, err)
            assert any(f'{m} {argv[1]}' in out for m in IN_MARKS), (argv, out)
            assert 'Zero Title' in out, (argv, out)


if __name__ == '__main__':
    sys.exit(_util.runner(_util.collect(dict(locals()))))
