import { del, get, list, put } from '@vercel/blob';
import {
  assertJobTransition,
  buildJobEvent,
  buildJobRequest,
  jobEventPath,
  jobLatestPath,
  jobRequestPath,
  latestJobEvent,
} from './_editorial_job_core.mjs';
import { isEditorialAdmin, isEditorialWriteAuthorized } from './_editorial_session_core.mjs';
import { attachmentPrefix } from './_editorial_attachment_core.mjs';

function json(response, status, payload) {
  response.status(status).setHeader('Cache-Control', 'no-store').json(payload);
}

function sameOrigin(request) {
  const origin = request.headers.origin;
  if (!origin) return true;
  try { return new URL(origin).host === request.headers.host; } catch { return false; }
}

async function readPrivateJson(blob) {
  const result = await get(typeof blob === 'string' ? blob : blob.url, { access: 'private' });
  if (!result || result.statusCode !== 200 || !result.stream) return null;
  return JSON.parse(await new Response(result.stream).text());
}

async function readJob(clientId, editionId, jobId) {
  const reference = { client_id: clientId, edition_id: editionId, job_id: jobId };
  const [job, latest] = await Promise.all([
    readPrivateJson(jobRequestPath(reference)),
    readPrivateJson(jobLatestPath(reference)),
  ]);
  if (!job) return null;
  if (latest) return { ...job, state: latest, history: [] };

  // Migrate jobs created before latest.json was introduced without penalizing new polls.
  const { blobs: events } = await list({ prefix: `editorial-job-events/${clientId}/${editionId}/${jobId}/`, limit: 100 });
  const history = (await Promise.all(events.map(readPrivateJson))).filter(Boolean);
  const state = latestJobEvent(history);
  if (state) {
    await put(jobLatestPath(reference), JSON.stringify(state, null, 2), {
      access: 'private', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json; charset=utf-8',
    });
  }
  return { ...job, state, history };
}

async function checkStorageAvailable() {
  const path = 'editorial-health/provider-probe.json';
  let result = await get(path, { access: 'private' });
  if (!result) {
    await put(path, JSON.stringify({ schema_version: 1, purpose: 'provider-health' }), {
      access: 'private', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json; charset=utf-8',
    });
    result = await get(path, { access: 'private' });
  }
  if (!result || result.statusCode !== 200 || !result.stream) throw new Error('Blob read probe failed');
  await result.stream.cancel().catch(() => null);
  return true;
}

async function listJobs(clientId, state) {
  const { blobs } = await list({ prefix: `editorial-jobs/${clientId}/`, limit: 1000 });
  const requests = (await Promise.all(blobs.filter((blob) => blob.pathname.endsWith('/request.json')).map(readPrivateJson))).filter(Boolean);
  const jobs = await Promise.all(requests.map((job) => readJob(job.client_id, job.edition_id, job.job_id)));
  return jobs
    .filter(Boolean)
    .filter((job) => !state || job.state?.state === state)
    .sort((left, right) => String(left.created_at).localeCompare(String(right.created_at)));
}

async function resolveAttachments(job) {
  const resolved = [];
  for (const reference of job.attachments || []) {
    const prefix = attachmentPrefix({
      client_id: job.client_id,
      edition_id: job.edition_id,
      article_slug: job.article_slug,
      attachment_id: reference.attachment_id,
    });
    const { blobs } = await list({ prefix, limit: 10 });
    const metadataBlob = blobs.find((blob) => blob.pathname.endsWith('/metadata.json'));
    const contentBlob = blobs.find((blob) => blob.pathname.endsWith('/content'));
    const metadata = metadataBlob ? await readPrivateJson(metadataBlob) : null;
    if (!metadata || !contentBlob) throw new Error(`Attachment ${reference.filename} is unavailable`);
    if (metadata.filename !== reference.filename || metadata.media_type !== reference.media_type || metadata.size_bytes !== reference.size_bytes) {
      throw new Error(`Attachment ${reference.filename} did not pass integrity checks`);
    }
    resolved.push(metadata);
  }
  return resolved;
}

export default async function handler(request, response) {
  if (request.method === 'GET' && request.query?.health === '1') {
    let storageAvailable = false;
    if (process.env.BLOB_READ_WRITE_TOKEN) {
      try {
        storageAvailable = await checkStorageAvailable();
      } catch (error) {
        console.error('[editorial-jobs] storage health failed', {
          message: String(error?.message || 'unknown storage error').slice(0, 240),
        });
      }
    }
    return json(response, 200, {
      ok: true,
      storage_configured: Boolean(process.env.BLOB_READ_WRITE_TOKEN),
      storage_available: storageAvailable,
      auth_configured: Boolean(process.env.RADAR_EDITORIAL_SAVE_TOKEN),
    });
  }
  if (!['GET', 'POST', 'PATCH'].includes(request.method)) {
    response.setHeader('Allow', 'GET, POST, PATCH');
    return json(response, 405, { ok: false, error: 'Method not allowed' });
  }
  if (!sameOrigin(request)) return json(response, 403, { ok: false, error: 'Cross-origin requests are not allowed' });
  if (!process.env.BLOB_READ_WRITE_TOKEN) return json(response, 503, { ok: false, error: 'Editorial job storage is not configured yet' });

  const secret = String(process.env.RADAR_EDITORIAL_SAVE_TOKEN || '').trim();
  const admin = isEditorialAdmin(request, secret);
  const authBody = request.method === 'GET' ? request.query : request.body;
  if (!admin && !isEditorialWriteAuthorized(request, authBody, secret)) {
    return json(response, 401, { ok: false, error: 'Editorial session unavailable' });
  }

  try {
    if (request.method === 'GET' && request.query?.worker_health === '1') {
      if (!admin) return json(response, 401, { ok: false, error: 'Operator authorization required' });
      const clientId = String(request.query?.client_id || '');
      if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(clientId)) return json(response, 400, { ok: false, error: 'Valid client_id required' });
      const { blobs } = await list({ prefix: `editorial-worker-heartbeats/${clientId}/`, limit: 100 });
      const heartbeats = (await Promise.all(blobs.map(readPrivateJson))).filter(Boolean);
      const latest = heartbeats.sort((left, right) => String(left.recorded_at).localeCompare(String(right.recorded_at))).at(-1) || null;
      const ageSeconds = latest ? Math.max(0, Math.round((Date.now() - Date.parse(latest.recorded_at)) / 1000)) : null;
      return json(response, 200, { ok: true, client_id: clientId, online: ageSeconds != null && ageSeconds <= 900, age_seconds: ageSeconds, latest });
    }
    if (request.method === 'POST') {
      if (request.body?.action === 'heartbeat') {
        if (!admin) return json(response, 401, { ok: false, error: 'Worker authorization required' });
        const clientId = String(request.body?.client_id || '');
        const workerId = String(request.body?.worker_id || '');
        if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(clientId) || !/^[a-z0-9][a-z0-9-]{0,79}$/.test(workerId)) {
          return json(response, 400, { ok: false, error: 'Valid client_id and worker_id required' });
        }
        const recordedAt = new Date().toISOString();
        const heartbeat = { schema_version: 1, client_id: clientId, worker_id: workerId, recorded_at: recordedAt };
        await put(`editorial-worker-heartbeats/${clientId}/${workerId}/latest.json`, JSON.stringify(heartbeat, null, 2), {
          access: 'private', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json; charset=utf-8',
        });
        return json(response, 200, { ok: true, recorded_at: recordedAt });
      }
      const job = buildJobRequest(request.body);
      job.attachments = await resolveAttachments(job);
      const active = (await listJobs(job.client_id)).find((item) =>
        item.edition_id === job.edition_id
        && item.article_slug === job.article_slug
        && ['queued', 'processing'].includes(item.state?.state),
      );
      if (active) return json(response, 409, { ok: false, error: 'An update for this article is already in progress', job_id: active.job_id });
      const queued = buildJobEvent({
        client_id: job.client_id,
        edition_id: job.edition_id,
        job_id: job.job_id,
        state: 'queued',
        message: 'Revision request saved',
      });
      await Promise.all([
        put(jobRequestPath(job), JSON.stringify(job, null, 2), { access: 'private', addRandomSuffix: false, contentType: 'application/json; charset=utf-8' }),
        put(jobEventPath(queued), JSON.stringify(queued, null, 2), { access: 'private', addRandomSuffix: false, contentType: 'application/json; charset=utf-8' }),
        put(jobLatestPath(queued), JSON.stringify(queued, null, 2), { access: 'private', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json; charset=utf-8' }),
      ]);
      return json(response, 202, { ok: true, job_id: job.job_id, state: 'queued', created_at: job.created_at });
    }

    const clientId = String(authBody?.client_id || '');
    const editionId = String(authBody?.edition_id || '');
    const jobId = String(authBody?.job_id || '');
    if (request.method === 'PATCH') {
      if (!admin) return json(response, 401, { ok: false, error: 'Worker authorization required' });
      const current = await readJob(clientId, editionId, jobId);
      if (!current) return json(response, 404, { ok: false, error: 'Editorial job not found' });
      assertJobTransition(current.state?.state || 'queued', String(request.body?.state || ''));
      const event = buildJobEvent(request.body);
      await Promise.all([
        put(jobEventPath(event), JSON.stringify(event, null, 2), {
          access: 'private', addRandomSuffix: false, contentType: 'application/json; charset=utf-8',
        }),
        put(jobLatestPath(event), JSON.stringify(event, null, 2), {
          access: 'private', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json; charset=utf-8',
        }),
      ]);
      if (event.state === 'completed' && current.attachments?.length) {
        const attachmentPaths = current.attachments.flatMap((item) => [item.blob_path, item.metadata_path]).filter(Boolean);
        if (attachmentPaths.length) await del(attachmentPaths).catch(() => null);
      }
      return json(response, 200, { ok: true, job_id: event.job_id, state: event.state, recorded_at: event.recorded_at });
    }

    if (jobId) {
      const job = await readJob(clientId, editionId, jobId);
      if (!job) return json(response, 404, { ok: false, error: 'Editorial job not found' });
      return json(response, 200, { ok: true, job });
    }
    if (!admin) return json(response, 400, { ok: false, error: 'job_id required' });
    const jobs = await listJobs(clientId, String(request.query?.state || ''));
    return json(response, 200, { ok: true, jobs });
  } catch (error) {
    const message = String(error?.message || 'Editorial job request failed').slice(0, 500);
    const storageUnavailable = /suspend|forbidden|storage/i.test(message);
    console.error('[editorial-jobs] request failed', {
      method: request.method,
      code: storageUnavailable ? 'EDITORIAL_STORAGE_UNAVAILABLE' : 'EDITORIAL_JOB_FAILED',
      message,
    });
    return json(response, storageUnavailable ? 503 : (request.method === 'GET' ? 500 : 400), {
      ok: false,
      code: storageUnavailable ? 'EDITORIAL_STORAGE_UNAVAILABLE' : 'EDITORIAL_JOB_FAILED',
      error: storageUnavailable
        ? 'Live revisions are temporarily unavailable. Your original draft is unchanged.'
        : 'RadarWire could not save this revision request. Your original draft is unchanged.',
    });
  }
}
