import test from 'node:test';
import assert from 'node:assert/strict';

import { buildRevisionRecord, revisionBlobPath, validateRevisionInput } from '../api/_editorial_revision_core.mjs';

function revision(overrides = {}) {
  return {
    client_id: 'amy-huffman',
    client_name: '1099FIRE',
    edition_id: 'edition-2026-08-14',
    article_slug: 'pre-filing-readiness',
    article_title: 'Pre-Filing Readiness',
    reading_mode: 'short',
    original_html: '<p>Original filing guidance.</p>',
    original_text: 'Original filing guidance.',
    edited_html: '<p>Amy edited the filing guidance.</p>',
    edited_text: 'Amy edited the filing guidance.',
    approval_status: 'submitted',
    voice_library_consent: false,
    consent_notice: 'Saved privately in RadarWire.',
    source_url: 'https://site-export-preview.vercel.app/reports/1099fire-weekly-review/article.html',
    ...overrides,
  };
}

test('builds immutable revision metadata and a private blob path', () => {
  const record = buildRevisionRecord(revision(), {
    now: new Date('2026-08-14T18:30:00.000Z'),
    revisionId: '12345678-1234-1234-1234-123456789abc',
  });

  assert.equal(record.changed, true);
  assert.equal(record.voice_library_eligible, false);
  assert.equal(record.edited_word_count, 5);
  assert.match(record.original_sha256, /^[a-f0-9]{64}$/);
  assert.equal(
    revisionBlobPath(record),
    'editorial-revisions/amy-huffman/edition-2026-08-14/pre-filing-readiness/2026-08-14T18-30-00-000Z-12345678-1234-1234-1234-123456789abc.json',
  );
});

test('requires explicit consent before a revision enters the voice library', () => {
  assert.throws(
    () => validateRevisionInput(revision({ approval_status: 'approved_final' })),
    /explicit voice-library consent/,
  );
  const approved = buildRevisionRecord(revision({ approval_status: 'approved_final', voice_library_consent: true }));
  assert.equal(approved.voice_library_eligible, true);
});

test('rejects unsafe identifiers and non-HTTPS source URLs', () => {
  assert.throws(() => validateRevisionInput(revision({ client_id: '../amy' })), /client_id/);
  assert.throws(() => validateRevisionInput(revision({ source_url: 'http://localhost/draft' })), /HTTPS/);
});

test('rejects active markup even when a client bypasses browser sanitization', () => {
  assert.throws(
    () => validateRevisionInput(revision({ edited_html: '<p onclick="sendSecret()">Unsafe</p>' })),
    /unsafe active markup/,
  );
  assert.throws(
    () => validateRevisionInput(revision({ original_html: '<a href="javascript:alert(1)">Unsafe</a>' })),
    /unsafe active markup/,
  );
  assert.doesNotThrow(() => validateRevisionInput(revision({ edited_html: '<p><a href="https://www.irs.gov/">Safe source</a></p>' })));
});
