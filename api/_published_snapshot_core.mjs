import { createHash } from 'node:crypto';

const CLIENT_HOSTS = {
  'amy-huffman': ['1099fire.com'],
};

export function validatePublishedPageUrl(clientId, value) {
  const allowed = CLIENT_HOSTS[clientId] || [];
  const url = new URL(String(value || ''));
  const hostname = url.hostname.toLowerCase().replace(/\.$/, '');
  if (url.protocol !== 'https:') throw new Error('Published page link must use HTTPS');
  if (!allowed.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`))) {
    throw new Error('Published page link must be on the client website');
  }
  if (url.username || url.password) throw new Error('Published page link cannot include credentials');
  return url;
}

export function publishedSnapshotPath(record, capturedAt = new Date()) {
  const stamp = capturedAt.toISOString().replace(/[:.]/g, '-');
  return `published-content/${record.client_id}/${record.article_slug}/${stamp}-${record.event_id}.html`;
}

export function publishedContentHash(content) {
  return createHash('sha256').update(content).digest('hex');
}
