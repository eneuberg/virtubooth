/** One QR code to print. The library knows nothing else about codes. */
export interface CodePrintInput {
  /** the full URL the QR encodes (with ?t=…) */
  url: string;
  /** the code's number, e.g. 2 */
  number: number;
  /** the code's name, e.g. "Gorilla 2" (printed small in the bottom right corner) */
  name: string;
  /** the party's name, e.g. "Lenas 30." */
  eventName: string;
  /** e.g. the activity title for a code that targets one */
  subtitle?: string | null;
}

/** A rectangle relative to a page: 0..1, origin top left. */
export interface RelRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The host's template: the PDF, the 0-based page and where the QR goes on it. */
export interface PosterTemplateInput {
  pdf: ArrayBuffer;
  page: number;
  rect: RelRect;
}
