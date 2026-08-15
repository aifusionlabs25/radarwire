import { createHmac, timingSafeEqual } from 'node:crypto';

export const EDITORIAL_SESSION_COOKIE = 'radar_editorial_session';
export const EDITORIAL_SESSION_MAX_AGE = 60 * 60 * 24 * 90;

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,79}$/;

function encode(value) {
  return Buffer.from(value, 'utf8').toString('base64url');
}

function sign(payload, secret) {
  return createHmac('sha256', secret).update(payload, 'utf8').digest('base64url');
}

function secureEqual(left, right) {
  const first = Buffer.from(left || '', 'utf8');
  const second = Buffer.from(right || '', 'utf8');
  return first.length === second.length && timingSafeEqual(first, second);
}

function validId(value) {
  return typeof value === 'string' && ID_PATTERN.test(value);
}

export function issueEditorialSession(secret, claims, { now = new Date(), maxAge = EDITORIAL_SESSION_MAX_AGE } = {}) {
  if (!secret) throw new Error('Session secret required');
  if (!validId(claims?.client_id) || !validId(claims?.edition_id)) throw new Error('Valid client and edition required');
  const issuedAt = Math.floor(now.getTime() / 1000);
  const payload = encode(JSON.stringify({
    version: 1,
    client_id: claims.client_id,
    edition_id: claims.edition_id,
    iat: issuedAt,
    exp: issuedAt + maxAge,
  }));
  return `${payload}.${sign(payload, secret)}`;
}

export function verifyEditorialSession(token, secret, expected = {}, { now = new Date() } = {}) {
  if (!token || !secret) return null;
  const [payload, signature, extra] = String(token).split('.');
  if (!payload || !signature || extra || !secureEqual(signature, sign(payload, secret))) return null;
  try {
    const claims = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    const nowSeconds = Math.floor(now.getTime() / 1000);
    if (claims.version !== 1 || !validId(claims.client_id) || !validId(claims.edition_id)) return null;
    if (!Number.isInteger(claims.iat) || !Number.isInteger(claims.exp) || claims.exp <= nowSeconds) return null;
    if (expected.client_id && claims.client_id !== expected.client_id) return null;
    if (expected.edition_id && claims.edition_id !== expected.edition_id) return null;
    return claims;
  } catch {
    return null;
  }
}

export function readCookie(cookieHeader, name) {
  const prefix = `${name}=`;
  return String(cookieHeader || '')
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length) || '';
}

export function isEditorialAdmin(request, secret) {
  const supplied = String(request?.headers?.authorization || '').replace(/^Bearer\s+/i, '').trim();
  return Boolean(secret) && secureEqual(supplied, secret);
}

export function isEditorialWriteAuthorized(request, body, secret) {
  if (isEditorialAdmin(request, secret)) return true;
  const token = readCookie(request?.headers?.cookie, EDITORIAL_SESSION_COOKIE);
  return Boolean(verifyEditorialSession(token, secret, {
    client_id: String(body?.client_id || ''),
    edition_id: String(body?.edition_id || ''),
  }));
}
