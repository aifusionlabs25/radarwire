import { randomUUID } from 'node:crypto';

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,79}$/;
const SCOPES = new Set(['both', 'short', 'full']);
const STATES = new Set(['queued', 'processing', 'completed', 'failed']);
const ACTIVE_HTML = [
  /<(?:script|style|iframe|object|embed|form|input|button|select|textarea|link|meta|base|svg|math)\b/i,
  /\son[a-z]+\s*=/i,
  /\ssrcdoc\s*=/i,
  /(?:javascript|vbscript)\s*:/i,
  /data\s*:\s*text\/html/i,
  /expression\s*\(/i,
];

const TRANSITIONS = {
  queued: new Set(['processing', 'failed']),
  processing: new Set(['completed', 'failed']),
  failed: new Set(['processing']),
  completed: new Set(),
};

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

function safeHtml(value, field) {
  const result = requiredString(value, field, 300000);
  if (ACTIVE_HTML.some((pattern) => pattern.test(result))) throw new Error(`${field} contains unsafe active markup`);
  return result;
}

function version(raw, mode) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error(`${mode} version is required`);
  return {
    html: safeHtml(raw.html, `${mode}.html`),
    text: requiredString(raw.text, `${mode}.text`, 160000),
  };
}

function attachment(raw, index) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error(`attachments[${index}] is invalid`);
  const size = Number(raw.size_bytes);
  if (!Number.isInteger(size) || size < 1 || size > 4 * 1024 * 1024) throw new Error(`attachments[${index}].size_bytes is invalid`);
  return {
    attachment_id: requiredId(raw.attachment_id, `attachments[${index}].attachment_id`),
    filename: requiredString(raw.filename, `attachments[${index}].filename`, 140),
    media_type: requiredString(raw.media_type, `attachments[${index}].media_type`, 120),
    size_bytes: size,
  };
}

function httpsUrl(value, field) {
  const parsed = new URL(requiredString(value, field, 1000));
  if (parsed.protocol !== 'https:') throw new Error(`${field} must use HTTPS`);
  return parsed.href;
}

export function validateJobRequest(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('JSON object required');
  const scope = requiredString(raw.scope || 'both', 'scope', 20);
  if (!SCOPES.has(scope)) throw new Error('scope must be both, short, or full');
  const versions = { short: version(raw.versions?.short, 'short') };
  if (raw.versions?.full) versions.full = version(raw.versions.full, 'full');
  if ((scope === 'both' || scope === 'full') && !versions.full) throw new Error('full version is required for this scope');
  const attachments = Array.isArray(raw.attachments) ? raw.attachments.map(attachment) : [];
  if (attachments.length > 3) throw new Error('No more than three attachments are allowed');
  return {
    schema_version: 1,
    client_id: requiredId(raw.client_id, 'client_id'),
    client_name: requiredString(raw.client_name, 'client_name', 120),
    edition_id: requiredId(raw.edition_id, 'edition_id'),
    article_slug: requiredId(raw.article_slug, 'article_slug'),
    article_title: requiredString(raw.article_title, 'article_title', 240),
    instruction: requiredString(raw.instruction, 'instruction', 2000),
    scope,
    versions,
    attachments,
    source_url: httpsUrl(raw.source_url, 'source_url'),
    truth_profile: requiredId(raw.truth_profile || '1099fire-v1', 'truth_profile'),
  };
}

export function buildJobRequest(raw, { now = new Date(), jobId = randomUUID() } = {}) {
  return {
    ...validateJobRequest(raw),
    job_id: jobId,
    created_at: now.toISOString(),
  };
}

export function validateJobEvent(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('JSON object required');
  const state = requiredString(raw.state, 'state', 20);
  if (!STATES.has(state)) throw new Error('state is invalid');
  const result = raw.result == null ? null : raw.result;
  if (state === 'completed' && (!result || typeof result !== 'object' || Array.isArray(result))) {
    throw new Error('completed state requires a result');
  }
  return {
    schema_version: 1,
    client_id: requiredId(raw.client_id, 'client_id'),
    edition_id: requiredId(raw.edition_id, 'edition_id'),
    job_id: requiredId(raw.job_id, 'job_id'),
    state,
    worker_id: raw.worker_id ? requiredId(raw.worker_id, 'worker_id') : null,
    message: raw.message ? requiredString(raw.message, 'message', 500) : null,
    result,
  };
}

export function buildJobEvent(raw, { now = new Date(), eventId = randomUUID() } = {}) {
  return { ...validateJobEvent(raw), event_id: eventId, recorded_at: now.toISOString() };
}

export function assertJobTransition(previousState, nextState) {
  if (!STATES.has(previousState) || !STATES.has(nextState) || !TRANSITIONS[previousState].has(nextState)) {
    throw new Error(`Invalid editorial job transition: ${previousState} to ${nextState}`);
  }
}

export function jobRequestPath(record) {
  return `editorial-jobs/${record.client_id}/${record.edition_id}/${record.job_id}/request.json`;
}

export function jobLatestPath(record) {
  return `editorial-jobs/${record.client_id}/${record.edition_id}/${record.job_id}/latest.json`;
}

export function jobEventPath(record) {
  const stamp = record.recorded_at.replace(/[:.]/g, '-');
  return `editorial-job-events/${record.client_id}/${record.edition_id}/${record.job_id}/${stamp}-${record.event_id}.json`;
}

export function latestJobEvent(events) {
  return [...events].sort((left, right) => String(left.recorded_at).localeCompare(String(right.recorded_at))).at(-1) || null;
}
