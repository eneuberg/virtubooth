/** A failure the admin can act on; its message is German and can be shown as it is. */
export class PrintError extends Error {
  override readonly name = 'PrintError';
}
