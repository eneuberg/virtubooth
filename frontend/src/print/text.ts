/**
 * Text for the PDFs: only the 14 standard fonts (Helvetica, Courier), so every string
 * must fit WinAnsi (Windows-1252). German umlauts and ß fit; emoji and most other
 * scripts do not and are dropped (letters with accents lose the accent first).
 */

/** The code points of Windows-1252 besides ASCII and Latin-1 (its 0x80–0x9F). */
const CP1252_EXTRA = new Set([
  0x20ac, 0x201a, 0x0192, 0x201e, 0x2026, 0x2020, 0x2021, 0x02c6, 0x2030, 0x0160, 0x2039, 0x0152, 0x017d,
  0x2018, 0x2019, 0x201c, 0x201d, 0x2022, 0x2013, 0x2014, 0x02dc, 0x2122, 0x0161, 0x203a, 0x0153, 0x017e,
  0x0178,
]);

/** Look-alikes outside WinAnsi, and letters without a decomposition, with a WinAnsi twin. */
const REPLACE = new Map<number, string>([
  [0x2010, '-'], // hyphen
  [0x2011, '-'], // non-breaking hyphen
  [0x2012, '–'], // figure dash → en dash
  [0x2015, '—'], // horizontal bar → em dash
  [0x2212, '-'], // minus sign
  [0x2032, "'"], // prime
  [0x2033, '"'], // double prime
  [0x201b, '‘'],
  [0x201f, '“'],
  [0x2027, '·'],
  [0x2044, '/'],
  [0x0141, 'L'], // Ł
  [0x0142, 'l'],
  [0x0110, 'D'], // Đ
  [0x0111, 'd'],
  [0x0126, 'H'], // Ħ
  [0x0127, 'h'],
  [0x0131, 'i'], // dotless i
  [0x0166, 'T'], // Ŧ
  [0x0167, 't'],
  [0x1e9e, 'SS'], // capital sharp s
]);

/** Whether Helvetica/Courier (WinAnsi encoding) can print this code point. */
export function isWinAnsi(cp: number): boolean {
  if (cp >= 0x20 && cp <= 0x7e) return true;
  if (cp >= 0xa0 && cp <= 0xff) return cp !== 0xad; // soft hyphen: invisible
  return CP1252_EXTRA.has(cp);
}

/**
 * A string the standard fonts can print: umlauts and common punctuation stay,
 * accents fall off letters WinAnsi lacks („Łódź“ → „Lódz“), emoji and other
 * scripts are dropped, whitespace collapses to single spaces.
 */
export function toWinAnsi(text: string): string {
  let out = '';
  for (const ch of text.normalize('NFC')) {
    const cp = ch.codePointAt(0) ?? 0;
    const mapped = REPLACE.get(cp);
    if (mapped !== undefined) {
      out += mapped;
    } else if (/\s/u.test(ch)) {
      out += ' ';
    } else if (isWinAnsi(cp)) {
      out += ch;
    } else {
      // the base letters without their combining marks (ő → o, ﬁ → fi)
      for (const part of ch.normalize('NFKD')) {
        if (isWinAnsi(part.codePointAt(0) ?? 0)) out += part;
      }
    }
  }
  return out.replace(/\s+/gu, ' ').trim();
}

const UMLAUTS: Record<string, string> = { ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss' };

/** For file names: lower case, ä→ae ö→oe ü→ue ß→ss, accents dropped, anything else "-". */
export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[äöüß]/gu, (c) => UMLAUTS[c] ?? c)
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
