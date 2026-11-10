const test = require('node:test');
const assert = require('node:assert/strict');
const { buildShareMessage } = require('../static/sharing.js');

test('email contains the personal key and public profile link', () => {
  const key = 'ssconf://vpn.example.test/keys/test.yaml';
  const result = buildShareMessage('alice', key, 'alice+vpn@example.com');
  const url = new URL(result.mailto);
  assert.equal(decodeURIComponent(url.pathname), 'alice+vpn@example.com');
  assert.equal(url.searchParams.get('subject'), result.subject);
  assert.equal(url.searchParams.get('body'), result.body);
  assert.ok(result.body.includes(key));
  assert.ok(result.body.includes('https://vpn.example.test/profiles/outline-dns.mobileconfig'));
  assert.ok(result.body.includes('Google encrypted DNS'));
});

test('recipient controls cannot inject additional mail headers', () => {
  for (const address of ['a@example.com\r\nBcc: victim@example.com', 'a@example.com,b@example.com', 'a@example.com;b@example.com']) {
    assert.throws(() => buildShareMessage('alice', 'ssconf://example.test/key', address));
  }
  const result = buildShareMessage('alice', 'ssconf://example.test/key', 'a?bcc=x@example.com');
  assert.equal(new URL(result.mailto).searchParams.has('bcc'), false);
});

test('copying instructions needs no recipient and invalid keys are rejected', () => {
  assert.equal(buildShareMessage('alice', 'ssconf://example.test/key').mailto, null);
  assert.throws(() => buildShareMessage('alice', 'javascript:alert(1)'));
});
