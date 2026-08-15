import test from 'node:test';
import assert from 'node:assert/strict';

import {
  publishedContentHash,
  publishedSnapshotPath,
  validatePublishedPageUrl,
} from '../api/_published_snapshot_core.mjs';

test('allows only HTTPS pages on the configured client website', () => {
  assert.equal(
    validatePublishedPageUrl('amy-huffman', 'https://www.1099fire.com/blog/filing-guide').hostname,
    'www.1099fire.com',
  );
  assert.throws(() => validatePublishedPageUrl('amy-huffman', 'http://1099fire.com/blog/post'), /HTTPS/);
  assert.throws(() => validatePublishedPageUrl('amy-huffman', 'https://example.com/blog/post'), /client website/);
  assert.throws(() => validatePublishedPageUrl('amy-huffman', 'https://1099fire.com.example.com/post'), /client website/);
});

test('creates a private snapshot path and content hash', () => {
  const record = { client_id: 'amy-huffman', article_slug: 'filing-guide', event_id: 'event-1' };
  assert.equal(
    publishedSnapshotPath(record, new Date('2026-08-15T17:30:00.000Z')),
    'published-content/amy-huffman/filing-guide/2026-08-15T17-30-00-000Z-event-1.html',
  );
  assert.match(publishedContentHash(Buffer.from('<html>saved</html>')), /^[a-f0-9]{64}$/);
});
