import { get, list, put } from '@vercel/blob';
import { buildStatusRecord, latestArticleStates, statusBlobPath } from './_editorial_status_core.mjs';
import { isEditorialAdmin, isEditorialWriteAuthorized } from './_editorial_session_core.mjs';
import {
  publishedContentHash,
  publishedSnapshotPath,
  validatePublishedPageUrl,
} from './_published_snapshot_core.mjs';

const MAX_PUBLISHED_PAGE_BYTES = 1024 * 1024;

function sameOrigin(request) {
  const origin = request.headers.origin;
  if (!origin) return true;
  try { return new URL(origin).host === request.headers.host; } catch { return false; }
}

function json(response, status, payload) {
  response.status(status).setHeader('Cache-Control', 'no-store').json(payload);
}

async function readPrivateJson(blob) {
  const result = await get(blob.url, { access: 'private' });
  if (!result || result.statusCode !== 200 || !result.stream) return null;
  return JSON.parse(await new Response(result.stream).text());
}

async function readLimitedBody(response) {
  const declared = Number(response.headers.get('content-length') || 0);
  if (declared > MAX_PUBLISHED_PAGE_BYTES) throw new Error('Published page is too large to archive');
  if (!response.body) throw new Error('Published page returned no content');
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_PUBLISHED_PAGE_BYTES) {
      await reader.cancel();
      throw new Error('Published page is too large to archive');
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks);
}

async function capturePublishedPage(record) {
  let current = validatePublishedPageUrl(record.client_id, record.published_url);
  const capturedAt = new Date();
  try {
    for (let redirects = 0; redirects <= 3; redirects += 1) {
      const response = await fetch(current, {
        redirect: 'manual',
        signal: AbortSignal.timeout(8000),
        headers: { 'User-Agent': 'RadarWire-Published-Archive/1.0' },
      });
      if (response.status >= 300 && response.status < 400 && response.headers.get('location')) {
        current = validatePublishedPageUrl(record.client_id, new URL(response.headers.get('location'), current).href);
        continue;
      }
      if (!response.ok) throw new Error(`Published page returned HTTP ${response.status}`);
      const contentType = String(response.headers.get('content-type') || '').toLowerCase();
      if (!contentType.includes('text/html')) throw new Error('Published page did not return HTML');
      const content = await readLimitedBody(response);
      const pathname = publishedSnapshotPath(record, capturedAt);
      await put(pathname, content, {
        access: 'private',
        addRandomSuffix: false,
        contentType: 'text/html; charset=utf-8',
      });
      return {
        status: 'saved',
        captured_at: capturedAt.toISOString(),
        final_url: current.href,
        blob_path: pathname,
        content_bytes: content.byteLength,
        content_sha256: publishedContentHash(content),
      };
    }
    throw new Error('Published page redirected too many times');
  } catch (error) {
    return {
      status: 'failed',
      attempted_at: capturedAt.toISOString(),
      error: String(error?.message || 'Unable to archive published page').slice(0, 240),
    };
  }
}

export default async function handler(request, response) {
  if (request.method === 'GET' && request.query?.health === '1') {
    return json(response, 200, {
      ok: true,
      storage_configured: Boolean(process.env.BLOB_READ_WRITE_TOKEN),
      auth_configured: Boolean(process.env.RADAR_EDITORIAL_SAVE_TOKEN),
    });
  }
  if (!['GET', 'POST'].includes(request.method)) {
    response.setHeader('Allow', 'GET, POST');
    return json(response, 405, { ok: false, error: 'Method not allowed' });
  }
  if (!sameOrigin(request)) return json(response, 403, { ok: false, error: 'Cross-origin requests are not allowed' });
  const secret = String(process.env.RADAR_EDITORIAL_SAVE_TOKEN || '').trim();
  if (request.method === 'GET' && !isEditorialAdmin(request, secret)) {
    return json(response, 401, { ok: false, error: 'Operator authorization required' });
  }
  if (request.method === 'POST' && !isEditorialWriteAuthorized(request, request.body, secret)) {
    return json(response, 401, { ok: false, error: 'Editorial session unavailable' });
  }
  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    return json(response, 503, { ok: false, error: 'Private editorial storage is not configured yet' });
  }

  if (request.method === 'POST') {
    try {
      let record = buildStatusRecord(request.body);
      if (record.status === 'published') {
        validatePublishedPageUrl(record.client_id, record.published_url);
        record = { ...record, published_snapshot: await capturePublishedPage(record) };
      }
      await put(statusBlobPath(record), JSON.stringify(record, null, 2), {
        access: 'private',
        addRandomSuffix: false,
        contentType: 'application/json; charset=utf-8',
      });
      return json(response, 201, {
        ok: true,
        event_id: record.event_id,
        recorded_at: record.recorded_at,
        status: record.status,
        published_snapshot_status: record.published_snapshot?.status || null,
      });
    } catch (error) {
      return json(response, 400, { ok: false, error: error.message || 'Invalid editorial status' });
    }
  }

  try {
    const clientId = String(request.query?.client_id || '');
    if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(clientId)) {
      return json(response, 400, { ok: false, error: 'Valid client_id required' });
    }
    const { blobs } = await list({ prefix: `editorial-status/${clientId}/`, limit: 1000 });
    const records = (await Promise.all(blobs.map(readPrivateJson)))
      .filter(Boolean)
      .sort((left, right) => String(left.recorded_at).localeCompare(String(right.recorded_at)));
    const latest = latestArticleStates(records);
    if (request.query?.format === 'jsonl') {
      response.status(200).setHeader('Cache-Control', 'no-store');
      response.setHeader('Content-Type', 'application/x-ndjson; charset=utf-8');
      return response.send(records.map((record) => JSON.stringify(record)).join('\n') + (records.length ? '\n' : ''));
    }
    return json(response, 200, { ok: true, client_id: clientId, event_count: records.length, latest });
  } catch {
    return json(response, 500, { ok: false, error: 'Unable to export the private editorial history' });
  }
}
