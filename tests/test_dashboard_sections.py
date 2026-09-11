#!/usr/bin/env python3
"""What two dashboard sections put on the wire, run rather than read.

The uploads browser and the eval panel are the two sections whose mistakes
leave the page: a link that carries the token into browser history, and a
command aimed at a tab the operator never chose. Each is mounted into a
small DOM in Node, driven through its own buttons, and judged on the
fetches it makes and the hrefs it renders.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dashnode  # noqa: E402
import _util  # noqa: E402
from _repo import ROOT  # noqa: E402


# Enough DOM for `h`, `field`, `clear` and the selectors each section uses.
# Every click on an element is recorded with the href it carried, so a
# synthesized download anchor is seen the same way a rendered one is.
_DOM = r"""
import { pathToFileURL } from 'node:url';
phase('dashboard harness started');
const clicks = [];
class El {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.text = '';
    this.attrs = {};
    this.listeners = {};
    this.style = {};
    this.dataset = {};
    this.className = '';
    this.id = '';
    this.disabled = false;
    this._value = '';
    this.classList = { add() {}, remove() {} };
  }
  get firstChild() { return this.children[0] || null; }
  get options() { return this.children.filter((c) => c.tag === 'option'); }
  get value() { return this._value; }
  set value(v) { this._value = String(v); }
  get textContent() {
    return this.text + this.children.map((c) => c.textContent).join('');
  }
  set textContent(v) { this.children = v === '' ? [] : [textNode(v)]; }
  set innerHTML(v) { this.children = []; this.text = ''; }
  appendChild(child) { this.children.push(child); return child; }
  append(...items) {
    for (const item of items) {
      this.children.push(item instanceof El ? item : textNode(item));
    }
  }
  removeChild(child) {
    this.children.splice(this.children.indexOf(child), 1);
    if (child.tag === 'option' && child.value === this._value) {
      this._value = '';
    }
    return child;
  }
  remove() {}
  focus() {}
  setAttribute(name, v) {
    this.attrs[name] = String(v);
    if (name === 'value') this._value = String(v);
  }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  click() {
    clicks.push({ tag: this.tag, text: this.textContent,
                  href: this.attrs.href, download: this.attrs.download });
    for (const fn of this.listeners.click || []) {
      fn({ currentTarget: this, preventDefault() {} });
    }
  }
  all() {
    const out = [];
    for (const c of this.children) out.push(c, ...c.all());
    return out;
  }
  find(selector) {
    if (!selector.startsWith('[data-role=')) {
      throw new Error('unsupported selector ' + selector);
    }
    const role = selector.slice(11, -1);
    return this.all().find((el) => el.dataset.role === role) || null;
  }
  querySelector(selector) { return this.find(selector); }
  byText(text) {
    return this.all().find(
      (el) => el.tag !== '#text' && el.textContent === text) || null;
  }
}
function textNode(value) {
  const node = new El('#text');
  node.text = String(value);
  return node;
}
globalThis.Node = El;
globalThis.document = {
  body: new El('body'),
  createElement: (tag) => new El(tag),
  createTextNode: textNode,
  getElementById: () => null,
  querySelector: () => new El('span'),
};
function jsonResponse(data) {
  return {
    ok: true, status: 200,
    headers: { get: () => 'application/json' },
    json: async () => data, text: async () => JSON.stringify(data),
  };
}
const token = 'dashboard-token';
globalThis.localStorage = {
  getItem: (key) => key === 'daedalus-token' ? token : '',
  setItem() {},
};
globalThis.setTimeout = (callback) => { callback(); return 0; };
globalThis.clearTimeout = () => {};
globalThis.setInterval = () => 0;
const settle = () => new Promise((resolve) => setImmediate(resolve));
"""


_UPLOADS_HARNESS = _dashnode.DashboardNodeHarness(_DOM + r"""
(async () => {
const fetched = [];
const listing = { total: 2, items: [
  { id: 'up1', filename: 'a&b#c.txt', size: 3, mtime: 1,
    path: token + '/up1/a&b#c.txt' },
  { id: 'up1', filename: 'shot.png', size: 4, mtime: 2,
    path: token + '/up1/shot.png' },
] };
globalThis.fetch = async (target, init) => {
  const headers = (init && init.headers) || {};
  fetched.push({ target: String(target), auth: headers.Authorization || '' });
  if (String(target).startsWith('/upload?limit=')) {
    return jsonResponse(listing);
  }
  return {
    ok: true, status: 200,
    headers: { get: () => 'application/octet-stream' },
    blob: async () => ({ from: String(target) }), json: async () => ({}),
  };
};
let held = 0;
URL.createObjectURL = () => 'blob:held-' + (++held);
URL.revokeObjectURL = () => {};
phase('dashboard module import started');
const { mount } = await bounded(
  import(pathToFileURL(process.argv[1]).href),
  'dashboard module import', _dashnodeStepTimeoutMs,
);
phase('dashboard module imported');
phase('dashboard call started');
const container = new El('div');
mount(container);
await bounded(settle(), 'uploads listing render', _dashnodeStepTimeoutMs);
const rendered = container.all().map((el) => el.attrs.href)
  .filter((href) => href !== undefined);
const afterRender = fetched.length;
container.byText('download').click();
await bounded(settle(), 'download fetch', _dashnodeStepTimeoutMs);
const downloadFetches = fetched.slice(afterRender);
container.byText('preview').click();
await bounded(settle(), 'preview fetch', _dashnodeStepTimeoutMs);
const previewFetches = fetched.slice(afterRender + downloadFetches.length);
phase('dashboard call settled');
process.stdout.write(JSON.stringify({
  rendered, downloadFetches, previewFetches, clicks,
}));
phase('dashboard harness finished');
})().catch(leave);
""", bounded_steps=4, module=True, arguments=(
    ROOT / 'dashboard' / 'sections' / 'uploads.js',))


def test_uploads_carry_the_token_in_a_header_and_never_in_a_link(_tmp):
    """Every file reaches the browser through the header-authenticated
    object-URL path, so no href on the page names the token or a route
    the bridge does not have, and an operator-named filename survives
    the trip percent-encoded."""
    result = _dashnode.run_dashboard_node(_UPLOADS_HARNESS)
    seen = json.loads(result.stdout)
    token = 'dashboard-token'
    hrefs = seen['rendered'] + [
        click['href'] for click in seen['clicks'] if click.get('href')]
    leaking = [href for href in hrefs
               if token in href or '/uploads/' in href]
    assert not leaking, leaking

    text_path = f'/upload?path={token}%2Fup1%2Fa%26b%23c.txt'
    assert [f['target'] for f in seen['downloadFetches']] == [text_path], seen
    image_path = f'/screenshot?path={token}%2Fup1%2Fshot.png'
    assert [f['target'] for f in seen['previewFetches']] == [image_path], seen
    for fetch in seen['downloadFetches'] + seen['previewFetches']:
        assert fetch['auth'] == f'Bearer {token}', fetch

    saved = [click for click in seen['clicks'] if click.get('download')]
    assert [click['download'] for click in saved] == ['a&b#c.txt'], seen
    assert all(click['href'].startswith('blob:') for click in saved), seen


def main():
    return _util.runner(_util.collect(globals()), tmp_prefix='dashsections_')


if __name__ == '__main__':
    raise SystemExit(main())
