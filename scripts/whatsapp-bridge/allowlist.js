import path from 'path';
import { existsSync, readFileSync } from 'fs';

export function normalizeWhatsAppIdentifier(value) {
  return String(value || '')
    .trim()
    .replace(/:.*@/, '@')
    .replace(/@.*/, '')
    .replace(/^\+/, '');
}

export function parseAllowedUsers(rawValue) {
  return new Set(
    String(rawValue || '')
      .split(',')
      .map((value) => normalizeWhatsAppIdentifier(value))
      .filter(Boolean)
  );
}

// Phone-number JIDs to resolve to LIDs. A LID passed as a phone simply resolves
// to nothing, so every all-digit entry is included.
export function phoneJidsForLidLookup(allowedUsers) {
  return [...allowedUsers]
    .filter((id) => /^\d{6,15}$/.test(id))
    .map((id) => `${id}@s.whatsapp.net`);
}

// Swaps the contents in place so every closure holding the Set sees the new
// list; a malformed payload throws before anything is cleared.
export function replaceAllowedUsers(allowedUsers, entries) {
  if (!Array.isArray(entries) || !entries.every((entry) => typeof entry === 'string')) {
    throw new TypeError('allowedUsers must be an array of strings');
  }
  const next = parseAllowedUsers(entries.join(','));
  allowedUsers.clear();
  for (const id of next) {
    allowedUsers.add(id);
  }
  return allowedUsers;
}

function readMappingFile(sessionDir, identifier, suffix = '') {
  const filePath = path.join(sessionDir, `lid-mapping-${identifier}${suffix}.json`);
  if (!existsSync(filePath)) {
    return null;
  }

  try {
    const parsed = JSON.parse(readFileSync(filePath, 'utf8'));
    const normalized = normalizeWhatsAppIdentifier(parsed);
    return normalized || null;
  } catch {
    return null;
  }
}

export function expandWhatsAppIdentifiers(identifier, sessionDir) {
  const normalized = normalizeWhatsAppIdentifier(identifier);
  if (!normalized) {
    return new Set();
  }

  // Walk both phone->LID and LID->phone mapping files so allowlists can use
  // either form transparently in bot mode.
  const resolved = new Set();
  const queue = [normalized];

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current || resolved.has(current)) {
      continue;
    }

    resolved.add(current);

    for (const suffix of ['', '_reverse']) {
      const mapped = readMappingFile(sessionDir, current, suffix);
      if (mapped && !resolved.has(mapped)) {
        queue.push(mapped);
      }
    }
  }

  return resolved;
}

export function matchesAllowedSender(senderId, senderAltId, allowedUsers, sessionDir) {
  // WhatsApp Multi-Device can expose a first-contact sender as an opaque LID
  // before it persists LID mapping files. Baileys supplies the same sender's
  // phone JID separately (key.remoteJidAlt for DMs, key.participantAlt in
  // groups), so consult it as an additional alias without changing the
  // allowlist itself (#63415, #72529).
  return matchesAllowedUser(senderId, allowedUsers, sessionDir)
    || matchesAllowedUser(senderAltId, allowedUsers, sessionDir);
}

export function matchesInboundWhatsAppGroup({
  chatId,
  groupPolicy,
  groupAllowedUsers,
  sessionDir,
}) {
  if (groupPolicy === 'disabled' || groupPolicy === 'pairing') {
    return false;
  }
  if (groupPolicy === 'allowlist') {
    return matchesAllowedUser(chatId, groupAllowedUsers, sessionDir);
  }
  return groupPolicy === 'open';
}

export function matchesAllowedUser(senderId, allowedUsers, sessionDir) {
  // Empty allowlist = NO ONE allowed (secure default, #8389).  Operators
  // who want an open bot must set ``WHATSAPP_ALLOWED_USERS=*`` explicitly.
  // Previous behaviour (empty → return true) let any stranger DM the
  // bridge and trigger a Python-side pairing-code reply.
  if (!allowedUsers || allowedUsers.size === 0) {
    return false;
  }

  // "*" means allow everyone (consistent with SIGNAL_GROUP_ALLOWED_USERS)
  if (allowedUsers.has('*')) {
    return true;
  }

  const aliases = expandWhatsAppIdentifiers(senderId, sessionDir);
  for (const alias of aliases) {
    if (allowedUsers.has(alias)) {
      return true;
    }
  }

  return false;
}
