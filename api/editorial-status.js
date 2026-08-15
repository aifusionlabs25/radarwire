import { timingSafeEqual } from 'node:crypto';
import { get, list, put } from '@vercel/blob';
import { buildStatusRecord, latestArticleStates, statusBlobPath } from './_editorial_status_core.mjs';

function secureEqual(left, right) {
  const first = Buffer.from(left || '', 'utf8');
  const second = Buffer.from(right || '', 'utf8');
  return first.length === second.length && timingSafeEqual(first, second);
}

function isAuthorized(request) {
  const expected = String(process.env.RADAR_EDITORIAL_SAVE_TOKEN || '').trim();
  const supplied = String(request.headers.authorization || '').replace(/^Bearer\s+/i, '').trim();
  return Boolean(expected) && secureEqual(supplied, expected);
}

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
  if (!isAuthorized(request)) return json(response, 401, { ok: false, error: 'Private review code not accepted' });
  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    return json(response, 503, { ok: false, error: 'Private editorial storage is not configured yet' });
  }

  if (request.method === 'POST') {
    try {
      const record = buildStatusRecord(request.body);
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
