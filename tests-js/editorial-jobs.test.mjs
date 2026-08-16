import test from 'node:test';
import assert from 'node:assert/strict';

import {
  assertJobTransition,
  buildJobEvent,
  buildJobRequest,
  jobEventPath,
  jobLatestPath,
  jobRequestPath,
  latestJobEvent,
  validateJobRequest,
} from '../api/_editorial_job_core.mjs';
import {
  attachmentPrefix,
  buildAttachmentMetadata,
  publicAttachmentMetadata,
  validateAttachmentBytes,
} from '../api/_editorial_attachment_core.mjs';

function request(overrides = {}) {
  return {
    client_id: 'amy-huffman',
    client_name: '1099FIRE',
    edition_id: 'edition-2026-08-14',
    article_slug: 'pre-filing-readiness',
    article_title: 'Pre-Filing Readiness',
    instruction: 'Remove every direct state filing reference.',
    scope: 'both',
    versions: {
      short: { html: '<p>Short draft.</p>', text: 'Short draft.' },
      full: { html: '<p>Full draft.</p>', text: 'Full draft.' },
    },
    source_url: 'https://site-export-preview.vercel.app/reports/1099fire-weekly-review/article.html',
    truth_profile: '1099fire-v1',
    ...overrides,
  };
}

test('builds an immutable dual-version job request', () => {
  const job = buildJobRequest(request(), {
    now: new Date('2026-08-16T15:00:00.000Z'),
    jobId: 'job-123',
  });
  assert.equal(job.scope, 'both');
  assert.equal(job.versions.full.text, 'Full draft.');
  assert.equal(jobRequestPath(job), 'editorial-jobs/amy-huffman/edition-2026-08-14/job-123/request.json');
  assert.equal(jobLatestPath(job), 'editorial-jobs/amy-huffman/edition-2026-08-14/job-123/latest.json');
});

test('requires both reading versions for coordinated changes', () => {
  assert.throws(() => validateJobRequest(request({ versions: { short: request().versions.short } })), /full version/);
  assert.doesNotThrow(() => validateJobRequest(request({ scope: 'short', versions: { short: request().versions.short } })));
});

test('rejects active markup and oversized instructions', () => {
  assert.throws(() => validateJobRequest(request({ versions: { ...request().versions, short: { html: '<script>x</script>', text: 'x' } } })), /unsafe/);
  assert.throws(() => validateJobRequest(request({ instruction: 'x'.repeat(2001) })), /2000/);
});

test('accepts no more than three bounded attachment references', () => {
  const attachment = { attachment_id: 'attachment-1', filename: 'notes.png', media_type: 'image/png', size_bytes: 1200 };
  assert.equal(validateJobRequest(request({ attachments: [attachment] })).attachments[0].filename, 'notes.png');
  assert.throws(() => validateJobRequest(request({ attachments: [attachment, attachment, attachment, attachment] })), /three/);
});

test('validates attachment signatures and builds private scoped paths', () => {
  const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a]);
  const record = buildAttachmentMetadata({
    client_id: 'amy-huffman', edition_id: 'edition-2026-08-14', article_slug: 'pre-filing-readiness',
    filename: 'screen%20note.png', media_type: 'image/png',
  }, png, { now: new Date('2026-08-16T15:00:00Z'), attachmentId: 'attachment-1' });
  assert.equal(record.filename, 'screen note.png');
  assert.match(record.blob_path, /editorial-attachments\/amy-huffman\/edition-2026-08-14\/pre-filing-readiness\/attachment-1\/content/);
  assert.deepEqual(publicAttachmentMetadata(record), {
    attachment_id: 'attachment-1', filename: 'screen note.png', media_type: 'image/png', size_bytes: png.length,
  });
  assert.match(attachmentPrefix(record), /attachment-1\/$/);
  assert.throws(() => validateAttachmentBytes(Buffer.from('not a pdf'), 'application/pdf'), /contents/);
  const sanitized = buildAttachmentMetadata({ ...record, filename: '..%2Fsecret.png' }, png, { attachmentId: 'attachment-2' });
  assert.equal(sanitized.filename, '..-secret.png');
  assert.doesNotMatch(sanitized.filename, /[\\/]/);
});

test('enforces bounded worker state transitions and event history', () => {
  assert.doesNotThrow(() => assertJobTransition('queued', 'processing'));
  assert.doesNotThrow(() => assertJobTransition('processing', 'completed'));
  assert.throws(() => assertJobTransition('queued', 'completed'), /Invalid/);
  const processing = buildJobEvent({ client_id: 'amy-huffman', edition_id: 'edition-2026-08-14', job_id: 'job-123', state: 'processing' }, { now: new Date('2026-08-16T15:01:00Z'), eventId: 'event-1' });
  const failed = buildJobEvent({ client_id: 'amy-huffman', edition_id: 'edition-2026-08-14', job_id: 'job-123', state: 'failed', message: 'Timed out' }, { now: new Date('2026-08-16T15:02:00Z'), eventId: 'event-2' });
  assert.equal(latestJobEvent([failed, processing]), failed);
  assert.match(jobEventPath(processing), /editorial-job-events\/amy-huffman\/edition-2026-08-14\/job-123\//);
});
