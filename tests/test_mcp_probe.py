#!/usr/bin/env python3
"""Suite for scripts/mcp_probe.py, the documented manual MCP client.

The probe is run as a subprocess against a stub that answers the way the
pinned MCP transport does, because the defect it pins was invisible to any
test that spoke to the probe's functions directly: the transport answers a
notification with 202 and no body, and the probe's helper read that body
as JSON.
"""
import contextlib
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402


PROBE = _util.ROOT / 'scripts' / 'mcp_probe.py'
TOKEN = 'probetok'
SESSION = 'probe-session'
TOOLS = [{'name': 'ping', 'description': 'Round-trip a document.title'}]


class _McpStubHandler(http.server.BaseHTTPRequestHandler):
    """A streamable-HTTP MCP endpoint reduced to what the probe sends it.

    `notifications/initialized` is answered 202 with an empty body, which
    is what mcp 2.1.1 does for a notification: there is no JSON-RPC id to
    answer, so there is nothing to put in a body.
    """

    seen = []

    def do_POST(self):  # noqa: N802  (http.server's spelling)
        length = int(self.headers.get('Content-Length') or 0)
        payload = json.loads(self.rfile.read(length) or b'{}')
        self.seen.append({
            'method': payload.get('method'),
            'session': self.headers.get('Mcp-Session-Id'),
            'authorization': self.headers.get('Authorization'),
        })
        method = payload.get('method')
        if method == 'notifications/initialized':
            self.send_response(202)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if method == 'initialize':
            result = {'protocolVersion': '2024-11-05', 'capabilities': {},
                      'serverInfo': {'name': 'stub', 'version': '0'}}
        elif method == 'tools/list':
            result = {'tools': TOOLS}
        elif method == 'tools/call':
            result = {'content': [{'type': 'text', 'text': json.dumps(
                {'echo': payload.get('params')})}]}
        else:
            result = {}
        body = json.dumps({'jsonrpc': '2.0', 'id': payload.get('id'),
                           'result': result}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Mcp-Session-Id', SESSION)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        del format, args


@contextlib.contextmanager
def _mcp_stub():
    _McpStubHandler.seen = []
    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _McpStubHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}/mcp'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _run_probe(url, *argv):
    if importlib.util.find_spec('httpx') is None:
        _util.skip('scripts/mcp_probe.py dependency (httpx) not installed')
    env = dict(os.environ, TOKEN=TOKEN, DAEDALUS_MCP_URL=url,
               PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run(
        [sys.executable, str(PROBE), *argv], cwd=str(_util.ROOT), env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=60)


def test_the_probe_survives_the_bodiless_answer_to_its_notification(tmp):
    """`list` reaches tools/list after the 202 that initialized earns.

    The transport answers `notifications/initialized` with 202 and no
    body. The probe's helper ended with `r.json()`, so the documented
    manual check died with a JSON decode traceback before it asked for a
    single tool, and the session id it had just been given went unused.
    """
    del tmp
    with _mcp_stub() as url:
        run = _run_probe(url, 'list')
        seen = list(_McpStubHandler.seen)
    assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
    assert 'ping' in run.stdout, run.stdout
    assert 'Round-trip a document.title' in run.stdout, run.stdout
    methods = [request['method'] for request in seen]
    assert methods == ['initialize', 'notifications/initialized',
                       'tools/list'], methods
    # The session the initialize answer opened carries through the
    # bodiless notification to the request that lists the tools.
    assert seen[2]['session'] == SESSION, seen
    assert seen[2]['authorization'] == f'Bearer {TOKEN}', seen


def test_the_probe_calls_a_tool_after_the_bodiless_notification(tmp):
    del tmp
    with _mcp_stub() as url:
        run = _run_probe(url, 'call', 'ping', '{"tab_id": "t1"}')
        seen = list(_McpStubHandler.seen)
    assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
    printed = json.loads(run.stdout)
    echoed = json.loads(printed['content'][0]['text'])
    assert echoed == {'echo': {'name': 'ping', 'arguments': {'tab_id': 't1'}}}
    methods = [request['method'] for request in seen]
    assert methods == ['initialize', 'notifications/initialized',
                       'tools/call'], methods
    assert seen[2]['session'] == SESSION, seen


if __name__ == '__main__':
    sys.exit(_util.runner(_util.collect(dict(locals()))))
