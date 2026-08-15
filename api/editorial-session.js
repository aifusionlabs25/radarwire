import {
  EDITORIAL_SESSION_COOKIE,
  EDITORIAL_SESSION_MAX_AGE,
  issueEditorialSession,
} from './_editorial_session_core.mjs';

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,79}$/;

function sameOrigin(request) {
  const origin = request.headers.origin;
  if (!origin) return true;
  try { return new URL(origin).host === request.headers.host; } catch { return false; }
}

function json(response, status, payload) {
  response.status(status).setHeader('Cache-Control', 'no-store').json(payload);
}

export default async function handler(request, response) {
  if (request.method !== 'GET') {
    response.setHeader('Allow', 'GET');
    return json(response, 405, { ok: false, error: 'Method not allowed' });
  }
  if (!sameOrigin(request)) return json(response, 403, { ok: false, error: 'Cross-origin requests are not allowed' });
  const secret = String(process.env.RADAR_EDITORIAL_SAVE_TOKEN || '').trim();
  if (!secret) return json(response, 503, { ok: false, error: 'Editorial saving is not configured yet' });

  const clientId = String(request.query?.client_id || '');
  const editionId = String(request.query?.edition_id || '');
  if (!ID_PATTERN.test(clientId) || !ID_PATTERN.test(editionId)) {
    return json(response, 400, { ok: false, error: 'Valid client and edition required' });
  }

  const token = issueEditorialSession(secret, { client_id: clientId, edition_id: editionId });
  response.setHeader('Set-Cookie', `${EDITORIAL_SESSION_COOKIE}=${token}; Path=/api/; Max-Age=${EDITORIAL_SESSION_MAX_AGE}; HttpOnly; Secure; SameSite=Strict`);
  return json(response, 200, { ok: true, expires_in_days: 90 });
}
