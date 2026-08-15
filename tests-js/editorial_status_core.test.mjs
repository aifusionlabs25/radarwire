import test from 'node:test';
import assert from 'node:assert/strict';

import { buildStatusRecord, latestArticleStates, statusBlobPath, validateStatusInput } from '../api/_editorial_status_core.mjs';

function status(overrides = {}) {
  return {
    client_id: 'amy-huffman',
    client_name: '1099FIRE',
    edition_id: 'edition-2026-08-14',
    article_slug: 'pre-filing-readiness',
    article_title: 'Pre-Filing Readiness',
    status: 'selected',
    source_url: 'https://site-export-preview.vercel.app/reports/1099fire-weekly-review/article.html',
    published_url: null,
    ...overrides,
  };
}

test('builds a private selected-topic event', () => {
  const record = buildStatusRecord(status(), {
    now: new Date('2026-08-15T16:00:00.000Z'),
    eventId: '12345678-1234-1234-1234-123456789abc',
  });
  assert.equal(record.status, 'selected');
  assert.match(record.article_fingerprint, /^[a-f0-9]{64}$/);
  assert.equal(
    statusBlobPath(record),
    'editorial-status/amy-huffman/edition-2026-08-14/pre-filing-readiness/2026-08-15T16-00-00-000Z-12345678-1234-1234-1234-123456789abc.json',
  );
});

test('published status requires an HTTPS published URL', () => {
  assert.throws(() => validateStatusInput(status({ status: 'published' })), /published_url is required/);
  assert.throws(() => validateStatusInput(status({ status: 'published', published_url: 'http://example.com/post' })), /HTTPS/);
  assert.equal(
    validateStatusInput(status({ status: 'published', published_url: 'https://1099fire.com/blog/post' })).published_url,
    'https://1099fire.com/blog/post',
  );
});

test('latest state reduces event history per article', () => {
  const first = buildStatusRecord(status(), { now: new Date('2026-08-15T16:00:00Z'), eventId: 'one' });
  const second = buildStatusRecord(status({ status: 'published', published_url: 'https://1099fire.com/blog/post' }), {
    now: new Date('2026-08-16T16:00:00Z'), eventId: 'two',
  });
  assert.deepEqual(latestArticleStates([second, first]), [second]);
});
