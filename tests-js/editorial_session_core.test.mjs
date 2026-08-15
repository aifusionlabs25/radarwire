import test from 'node:test';
import assert from 'node:assert/strict';

import {
  EDITORIAL_SESSION_COOKIE,
  isEditorialWriteAuthorized,
  issueEditorialSession,
  verifyEditorialSession,
} from '../api/_editorial_session_core.mjs';

const secret = 'test-secret-with-enough-entropy';
const claims = { client_id: 'amy-huffman', edition_id: 'edition-2026-08-14' };
const issuedAt = new Date('2026-08-15T12:00:00Z');

test('issues and verifies a scoped editorial session', () => {
  const token = issueEditorialSession(secret, claims, { now: issuedAt, maxAge: 3600 });
  const verified = verifyEditorialSession(token, secret, claims, { now: new Date('2026-08-15T12:30:00Z') });
  assert.equal(verified.client_id, claims.client_id);
  assert.equal(verified.edition_id, claims.edition_id);
});

test('rejects tampered, expired, and mismatched sessions', () => {
  const token = issueEditorialSession(secret, claims, { now: issuedAt, maxAge: 60 });
  assert.equal(verifyEditorialSession(`${token}x`, secret, claims, { now: issuedAt }), null);
  assert.equal(verifyEditorialSession(token, secret, claims, { now: new Date('2026-08-15T12:02:00Z') }), null);
  assert.equal(verifyEditorialSession(token, secret, { ...claims, edition_id: 'another-edition' }, { now: issuedAt }), null);
});

test('authorizes a matching cookie or operator bearer token', () => {
  const token = issueEditorialSession(secret, claims);
  const cookieRequest = { headers: { cookie: `${EDITORIAL_SESSION_COOKIE}=${token}` } };
  assert.equal(isEditorialWriteAuthorized(cookieRequest, claims, secret), true);
  assert.equal(isEditorialWriteAuthorized(cookieRequest, { ...claims, client_id: 'another-client' }, secret), false);
  assert.equal(isEditorialWriteAuthorized({ headers: { authorization: `Bearer ${secret}` } }, claims, secret), true);
});
