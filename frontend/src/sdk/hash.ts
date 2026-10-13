/**
 * Hex SHA-256 of a string. Plain http on a LAN IP has no `crypto.subtle`; then two
 * FNV-1a passes stand in, repeated to 64 hex characters (the server only checks the
 * shape, ^[0-9a-f]{16,64}$). Port of vb.js / device.js sha256Hex().
 */
export async function sha256Hex(text: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    try {
      const buf = await subtle.digest('SHA-256', new TextEncoder().encode(text));
      return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
    } catch {
      // some embedded browsers expose subtle but refuse to digest: fall through
    }
  }
  return fnvHex(text);
}

/** The insecure-context fallback, exported for tests. */
export function fnvHex(text: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0x5bd1e995;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ c, 0x5bd1e995) >>> 0;
  }
  return (h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0')).repeat(4);
}
