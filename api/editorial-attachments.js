import { del, get, list, put } from '@vercel/blob';
import {
  attachmentPrefix,
  buildAttachmentMetadata,
  MAX_ATTACHMENT_BYTES,
  publicAttachmentMetadata,
} from './_editorial_attachment_core.mjs';
import { isEditorialAdmin, isEditorialWriteAuthorized } from './_editorial_session_core.mjs';

export const config = { api: { bodyParser: false } };

function json(response, status, payload) {
  response.status(status).setHeader('Cache-Control', 'no-store').json(payload);
}

function sameOrigin(request) {
  const origin = request.headers.origin;
  if (!origin) return true;
  try { return new URL(origin).host === request.headers.host; } catch { return false; }
}

async function readBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_ATTACHMENT_BYTES) throw new Error('Attachment must be smaller than 4 MB');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function readPrivateJson(blob) {
  const result = await get(blob.url, { access: 'private' });
  if (!result || result.statusCode !== 200 || !result.stream) return null;
  return JSON.parse(await new Response(result.stream).text());
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

async function findAttachment(query) {
  const prefix = attachmentPrefix(query);
  const { blobs } = await list({ prefix, limit: 10 });
  const metadataBlob = blobs.find((blob) => blob.pathname.endsWith('/metadata.json'));
  const contentBlob = blobs.find((blob) => blob.pathname.endsWith('/content'));
  const metadata = metadataBlob ? await readPrivateJson(metadataBlob) : null;
  return metadata && contentBlob ? { metadata, metadataBlob, contentBlob } : null;
}

export default async function handler(request, response) {
  if (request.method === 'GET' && request.query?.health === '1') {
    let storageAvailable = false;
    if (process.env.BLOB_READ_WRITE_TOKEN) {
      try {
        storageAvailable = await checkStorageAvailable();
      } catch (error) {
        console.error('[editorial-attachments] storage health failed', {
          message: String(error?.message || 'unknown storage error').slice(0, 240),
        });
      }
    }
    return json(response, 200, {
      ok: true,
      storage_configured: Boolean(process.env.BLOB_READ_WRITE_TOKEN),
      storage_available: storageAvailable,
      auth_configured: Boolean(process.env.RADAR_EDITORIAL_SAVE_TOKEN),
      max_attachment_bytes: MAX_ATTACHMENT_BYTES,
    });
  }
  if (!['GET', 'POST', 'DELETE'].includes(request.method)) {
    response.setHeader('Allow', 'GET, POST, DELETE');
    return json(response, 405, { ok: false, error: 'Method not allowed' });
  }
  if (!sameOrigin(request)) return json(response, 403, { ok: false, error: 'Cross-origin requests are not allowed' });
  if (!process.env.BLOB_READ_WRITE_TOKEN) return json(response, 503, { ok: false, error: 'Editorial attachment storage is not configured yet' });

  const secret = String(process.env.RADAR_EDITORIAL_SAVE_TOKEN || '').trim();
  const admin = isEditorialAdmin(request, secret);
  const auth = request.query || {};
  if (!admin && !isEditorialWriteAuthorized(request, auth, secret)) {
    return json(response, 401, { ok: false, error: 'Editorial session unavailable' });
  }

  try {
    if (request.method === 'POST') {
      const bytes = await readBody(request);
      const metadata = buildAttachmentMetadata({
        client_id: request.query?.client_id,
        edition_id: request.query?.edition_id,
        article_slug: request.query?.article_slug,
        filename: request.headers['x-radar-filename'],
        media_type: request.headers['content-type'],
      }, bytes);
      await Promise.all([
        put(metadata.blob_path, bytes, { access: 'private', addRandomSuffix: false, contentType: metadata.media_type }),
        put(metadata.metadata_path, JSON.stringify(metadata, null, 2), { access: 'private', addRandomSuffix: false, contentType: 'application/json; charset=utf-8' }),
      ]);
      return json(response, 201, { ok: true, attachment: publicAttachmentMetadata(metadata) });
    }

    const attachment = await findAttachment(request.query || {});
    if (!attachment) return json(response, 404, { ok: false, error: 'Attachment not found' });
    if (request.method === 'DELETE') {
      await del([attachment.metadataBlob.url, attachment.contentBlob.url]);
      return json(response, 200, { ok: true, deleted: true });
    }
    if (!admin) return json(response, 401, { ok: false, error: 'Worker authorization required' });
    const result = await get(attachment.contentBlob.url, { access: 'private' });
    if (!result || result.statusCode !== 200 || !result.stream) return json(response, 404, { ok: false, error: 'Attachment content not found' });
    response.status(200);
    response.setHeader('Cache-Control', 'no-store');
    response.setHeader('Content-Type', attachment.metadata.media_type);
    response.setHeader('Content-Length', String(attachment.metadata.size_bytes));
    response.setHeader('Content-Disposition', `attachment; filename="${attachment.metadata.filename.replace(/["\\]/g, '_')}"`);
    const bytes = Buffer.from(await new Response(result.stream).arrayBuffer());
    return response.end(bytes);
  } catch (error) {
    const message = String(error?.message || 'Attachment request failed').slice(0, 500);
    const storageUnavailable = /suspend|forbidden|storage/i.test(message);
    console.error('[editorial-attachments] request failed', {
      method: request.method,
      code: storageUnavailable ? 'ATTACHMENT_STORAGE_UNAVAILABLE' : 'ATTACHMENT_REQUEST_FAILED',
      message,
    });
    return json(response, storageUnavailable ? 503 : 400, {
      ok: false,
      code: storageUnavailable ? 'ATTACHMENT_STORAGE_UNAVAILABLE' : 'ATTACHMENT_REQUEST_FAILED',
      error: storageUnavailable
        ? 'Attachments are temporarily unavailable. Your typed request has not been lost.'
        : 'RadarWire could not attach that file. Remove it and try again.',
    });
  }
}
