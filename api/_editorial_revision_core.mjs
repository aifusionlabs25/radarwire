import { createHash, randomUUID } from 'node:crypto';

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,79}$/;
const MODES = new Set(['short', 'full']);
const STATUSES = new Set(['submitted', 'approved_final']);

function requiredString(value, field, maxLength) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${field} is required`);
  }
  if (value.length > maxLength) {
    throw new Error(`${field} exceeds ${maxLength} characters`);
  }
  return value.trim();
}

function requiredId(value, field) {
  const result = requiredString(value, field, 80);
  if (!ID_PATTERN.test(result)) {
    throw new Error(`${field} must use lowercase letters, numbers, and hyphens`);
  }
  return result;
}

function digest(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

function wordCount(value) {
  return value.trim() ? value.trim().split(/\s+/).length : 0;
}

export function validateRevisionInput(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error('JSON object required');
  }
  const sourceUrl = requiredString(raw.source_url, 'source_url', 1000);
  const parsedUrl = new URL(sourceUrl);
  if (parsedUrl.protocol !== 'https:') {
    throw new Error('source_url must use HTTPS');
  }
  const readingMode = requiredString(raw.reading_mode, 'reading_mode', 20);
  if (!MODES.has(readingMode)) throw new Error('reading_mode must be short or full');
  const approvalStatus = requiredString(raw.approval_status, 'approval_status', 30);
  if (!STATUSES.has(approvalStatus)) throw new Error('approval_status is invalid');
  const voiceLibraryConsent = raw.voice_library_consent === true;
  if (approvalStatus === 'approved_final' && !voiceLibraryConsent) {
    throw new Error('approved_final requires explicit voice-library consent');
  }
  return {
    schema_version: 1,
    client_id: requiredId(raw.client_id, 'client_id'),
    client_name: requiredString(raw.client_name, 'client_name', 120),
    edition_id: requiredId(raw.edition_id, 'edition_id'),
    article_slug: requiredId(raw.article_slug, 'article_slug'),
    article_title: requiredString(raw.article_title, 'article_title', 240),
    reading_mode: readingMode,
    original_html: requiredString(raw.original_html, 'original_html', 300000),
    original_text: requiredString(raw.original_text, 'original_text', 160000),
    edited_html: requiredString(raw.edited_html, 'edited_html', 300000),
    edited_text: requiredString(raw.edited_text, 'edited_text', 160000),
    approval_status: approvalStatus,
    voice_library_consent: voiceLibraryConsent,
    consent_notice: requiredString(raw.consent_notice, 'consent_notice', 500),
    source_url: parsedUrl.href,
  };
}

export function buildRevisionRecord(raw, { now = new Date(), revisionId = randomUUID() } = {}) {
  const input = validateRevisionInput(raw);
  const originalHash = digest(input.original_text);
  const editedHash = digest(input.edited_text);
  return {
    ...input,
    revision_id: revisionId,
    saved_at: now.toISOString(),
    original_sha256: originalHash,
    edited_sha256: editedHash,
    changed: originalHash !== editedHash,
    original_word_count: wordCount(input.original_text),
    edited_word_count: wordCount(input.edited_text),
    voice_library_eligible: input.approval_status === 'approved_final' && input.voice_library_consent,
  };
}

export function revisionBlobPath(record) {
  const stamp = record.saved_at.replace(/[:.]/g, '-');
  return `editorial-revisions/${record.client_id}/${record.edition_id}/${record.article_slug}/${stamp}-${record.revision_id}.json`;
}
