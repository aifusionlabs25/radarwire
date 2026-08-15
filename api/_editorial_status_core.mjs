import { createHash, randomUUID } from 'node:crypto';

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,79}$/;
const STATUSES = new Set(['selected', 'published']);

function requiredString(value, field, maxLength) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} is required`);
  if (value.length > maxLength) throw new Error(`${field} exceeds ${maxLength} characters`);
  return value.trim();
}

function requiredId(value, field) {
  const result = requiredString(value, field, 80);
  if (!ID_PATTERN.test(result)) throw new Error(`${field} must use lowercase letters, numbers, and hyphens`);
  return result;
}

function httpsUrl(value, field) {
  const parsed = new URL(requiredString(value, field, 1000));
  if (parsed.protocol !== 'https:') throw new Error(`${field} must use HTTPS`);
  return parsed.href;
}

export function validateStatusInput(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('JSON object required');
  const status = requiredString(raw.status, 'status', 20);
  if (!STATUSES.has(status)) throw new Error('status must be selected or published');
  const publishedUrl = raw.published_url ? httpsUrl(raw.published_url, 'published_url') : null;
  if (status === 'published' && !publishedUrl) throw new Error('published_url is required when status is published');
  return {
    schema_version: 1,
    client_id: requiredId(raw.client_id, 'client_id'),
    client_name: requiredString(raw.client_name, 'client_name', 120),
    edition_id: requiredId(raw.edition_id, 'edition_id'),
    article_slug: requiredId(raw.article_slug, 'article_slug'),
    article_title: requiredString(raw.article_title, 'article_title', 240),
    status,
    source_url: httpsUrl(raw.source_url, 'source_url'),
    published_url: publishedUrl,
  };
}

export function buildStatusRecord(raw, { now = new Date(), eventId = randomUUID() } = {}) {
  const input = validateStatusInput(raw);
  return {
    ...input,
    event_id: eventId,
    recorded_at: now.toISOString(),
    article_fingerprint: createHash('sha256')
      .update(`${input.client_id}\n${input.article_slug}\n${input.article_title}`, 'utf8')
      .digest('hex'),
  };
}

export function statusBlobPath(record) {
  const stamp = record.recorded_at.replace(/[:.]/g, '-');
  return `editorial-status/${record.client_id}/${record.edition_id}/${record.article_slug}/${stamp}-${record.event_id}.json`;
}

export function latestArticleStates(records) {
  const states = new Map();
  [...records]
    .sort((left, right) => String(left.recorded_at).localeCompare(String(right.recorded_at)))
    .forEach((record) => states.set(`${record.edition_id}/${record.article_slug}`, record));
  return [...states.values()];
}
