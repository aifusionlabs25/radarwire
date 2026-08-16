import { randomUUID } from 'node:crypto';

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,79}$/;
export const MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024;
export const ALLOWED_ATTACHMENT_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/webp',
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
]);

function requiredId(value, field) {
  const result = String(value || '').trim();
  if (!ID_PATTERN.test(result)) throw new Error(`${field} is invalid`);
  return result;
}

function safeFilename(value) {
  let decoded;
  try { decoded = decodeURIComponent(String(value || '')); } catch { throw new Error('Attachment filename is invalid'); }
  const name = decoded.replace(/[\\/\u0000-\u001f\u007f]+/g, '-').trim();
  if (!name || name.length > 140 || name === '.' || name === '..') throw new Error('Attachment filename is invalid');
  return name;
}

function hasSignature(bytes, signature, offset = 0) {
  return signature.every((value, index) => bytes[offset + index] === value);
}

export function validateAttachmentBytes(bytes, mediaType) {
  if (!Buffer.isBuffer(bytes) || bytes.length < 1) throw new Error('Attachment is empty');
  if (bytes.length > MAX_ATTACHMENT_BYTES) throw new Error('Attachment must be smaller than 4 MB');
  if (!ALLOWED_ATTACHMENT_TYPES.has(mediaType)) throw new Error('Attachment type is not supported');
  const valid = mediaType === 'image/png' ? hasSignature(bytes, [0x89, 0x50, 0x4e, 0x47])
    : mediaType === 'image/jpeg' ? hasSignature(bytes, [0xff, 0xd8, 0xff])
      : mediaType === 'image/webp' ? hasSignature(bytes, [0x52, 0x49, 0x46, 0x46]) && bytes.subarray(8, 12).toString('ascii') === 'WEBP'
        : mediaType === 'application/pdf' ? bytes.subarray(0, 5).toString('ascii') === '%PDF-'
          : mediaType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ? hasSignature(bytes, [0x50, 0x4b, 0x03, 0x04])
            : !bytes.includes(0);
  if (!valid) throw new Error('Attachment contents do not match the declared file type');
}

export function buildAttachmentMetadata(raw, bytes, { now = new Date(), attachmentId = randomUUID() } = {}) {
  const mediaType = String(raw.media_type || '').split(';')[0].trim().toLowerCase();
  validateAttachmentBytes(bytes, mediaType);
  const record = {
    schema_version: 1,
    attachment_id: requiredId(attachmentId, 'attachment_id'),
    client_id: requiredId(raw.client_id, 'client_id'),
    edition_id: requiredId(raw.edition_id, 'edition_id'),
    article_slug: requiredId(raw.article_slug, 'article_slug'),
    filename: safeFilename(raw.filename),
    media_type: mediaType,
    size_bytes: bytes.length,
    created_at: now.toISOString(),
  };
  return {
    ...record,
    blob_path: `editorial-attachments/${record.client_id}/${record.edition_id}/${record.article_slug}/${record.attachment_id}/content`,
    metadata_path: `editorial-attachments/${record.client_id}/${record.edition_id}/${record.article_slug}/${record.attachment_id}/metadata.json`,
  };
}

export function publicAttachmentMetadata(record) {
  return {
    attachment_id: record.attachment_id,
    filename: record.filename,
    media_type: record.media_type,
    size_bytes: record.size_bytes,
  };
}

export function attachmentPrefix(raw) {
  return `editorial-attachments/${requiredId(raw.client_id, 'client_id')}/${requiredId(raw.edition_id, 'edition_id')}/${requiredId(raw.article_slug, 'article_slug')}/${requiredId(raw.attachment_id, 'attachment_id')}/`;
}
