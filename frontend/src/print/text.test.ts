import { PDFDocument, StandardFonts } from '@cantoo/pdf-lib';
import { describe, expect, it } from 'vitest';
import { exportFileName } from './names';
import { isWinAnsi, slug, toWinAnsi } from './text';

const code = (name: string, number: number) => ({
  url: 'https://x.example/?t=a',
  number,
  name,
  eventName: 'Party',
});

describe('toWinAnsi', () => {
  it('keeps German text and common punctuation', () => {
    expect(toWinAnsi('Lenas 30. – „Größte Fete“ für Ärzte & Öko-Übermut!')).toBe(
      'Lenas 30. – „Größte Fete“ für Ärzte & Öko-Übermut!',
    );
    expect(toWinAnsi('Café € 5 … ‘ok’ • ß')).toBe('Café € 5 … ‘ok’ • ß');
  });

  it('drops emoji and unsupported scripts, collapses spaces', () => {
    expect(toWinAnsi('  Party 🎉🍻  im\tGarten 👨‍👩‍👧 ')).toBe('Party im Garten');
    expect(toWinAnsi('Привет Lena 你好')).toBe('Lena');
    expect(toWinAnsi('🎉')).toBe('');
  });

  it('keeps the base letter of accented letters WinAnsi lacks', () => {
    expect(toWinAnsi('Łódź, Őrség, Dvořák, ﬁ①, ẞ')).toBe('Lódz, Orség, Dvorák, fi1, SS');
    // decomposed umlauts are composed first
    expect(toWinAnsi('Müller')).toBe('Müller');
    expect(toWinAnsi('a‐b−c d​e')).toBe('a-b-c de');
  });

  it('produces only what Helvetica (WinAnsi) can encode', async () => {
    const doc = await PDFDocument.create();
    const font = await doc.embedFont(StandardFonts.Helvetica);
    const nasty = 'Zoë 🍕 Łukasz — „30“ ™ ½ ​‍ Ω ∑ ✓ ẞ ǅ ﬁ ① ­ \u0007';
    const text = toWinAnsi(nasty);
    expect(() => font.encodeText(text)).not.toThrow();
    for (const ch of text) expect(isWinAnsi(ch.codePointAt(0) ?? 0)).toBe(true);
    expect(text).toContain('Zoë');
    expect(text).toContain('„30“ ™ ½');
  });
});

describe('slug and file names', () => {
  it('slugs lower case with German transliteration', () => {
    expect(slug('Gorilla')).toBe('gorilla');
    expect(slug('Größe Übel Ärger')).toBe('groesse-uebel-aerger');
    expect(slug('Café  & Bar!')).toBe('cafe-bar');
    expect(slug('🎉')).toBe('');
  });

  it('names the files', () => {
    expect(exportFileName(code('Gorilla 2', 2), 'png')).toBe('qr-02-gorilla.png');
    expect(exportFileName(code('Gorilla 2', 2), 'qr-pdf')).toBe('qr-02-gorilla-gross.pdf');
    expect(exportFileName(code('Gorilla 2', 2), 'poster')).toBe('plakat-02-gorilla.pdf');
    expect(exportFileName(code('Muster 0', 0), 'poster')).toBe('plakat-00-muster.pdf');
    expect(exportFileName(code('Großer Bär 12', 12), 'png')).toBe('qr-12-grosser-baer.png');
    expect(exportFileName(code('Seehund 104', 104), 'png')).toBe('qr-104-seehund.png');
  });

  it('keeps other numbers in the name and copes with empty slugs', () => {
    expect(exportFileName(code('Gorilla 12', 2), 'png')).toBe('qr-02-gorilla-12.png');
    expect(exportFileName(code('Eingang', 3), 'png')).toBe('qr-03-eingang.png');
    expect(exportFileName(code('🎉 7', 7), 'png')).toBe('qr-07.png');
  });
});
