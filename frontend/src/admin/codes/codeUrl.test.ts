import { describe, expect, it } from 'vitest';
import {
  codeUrl,
  countText,
  NO_TOKEN_IN_LINK,
  readTokenInput,
  revokedTitle,
  scansText,
  targetFromLinkNote,
  targetLabel,
  targetOfPath,
  TOKEN_INVALID,
  TOKEN_TOO_SIMPLE,
  tokenProblem,
} from './codeUrl';

const TOKEN = 'printed-token-0123456789';
const activities = new Map([
  ['booth', { title: 'Fotobox' }],
  ['beer', { title: 'Beer Cam' }],
]);
const ctx = { partyOrigin: 'https://party.example', activities };

describe('the URL of a code', () => {
  it('is the public base URL (or this origin) plus the entry path', () => {
    expect(codeUrl('https://party.example', `/?t=${TOKEN}`, 'http://localhost:8000')).toBe(
      `https://party.example/?t=${TOKEN}`,
    );
    expect(codeUrl('https://party.example/', '/x/booth/?t=abc', 'x')).toBe(
      'https://party.example/x/booth/?t=abc',
    );
    expect(codeUrl(null, '/?t=abc', 'http://192.168.1.5:8000')).toBe('http://192.168.1.5:8000/?t=abc');
    expect(codeUrl('', '/?t=abc', 'http://localhost')).toBe('http://localhost/?t=abc');
  });
});

describe('token rules (as the server)', () => {
  it.each([
    ['short', TOKEN_INVALID],
    ['has spaces in the token', TOKEN_INVALID],
    ['umlaut-token-äöü-xyz', TOKEN_INVALID],
    ['x'.repeat(129), TOKEN_INVALID],
    ['abababababababab', TOKEN_TOO_SIMPLE],
    ['abcdeabcdeabcdeabcde', TOKEN_TOO_SIMPLE],
    ['abcdefabcdefabcd', null],
    [TOKEN, null],
  ])('%s', (token, problem) => {
    expect(tokenProblem(token)).toBe(problem);
  });
});

describe('a pasted token or link', () => {
  it('takes a bare token as it is', () => {
    expect(readTokenInput(`  ${TOKEN} `, ctx)).toEqual({
      token: TOKEN,
      error: null,
      warning: null,
      target: null,
    });
    expect(readTokenInput('too short', ctx).error).toBe(TOKEN_INVALID);
    expect(readTokenInput('', ctx).error).toBe(TOKEN_INVALID);
  });

  it('takes t from a link and the activity from its path', () => {
    expect(readTokenInput(`https://party.example/x/booth/?t=${TOKEN}`, ctx)).toEqual({
      token: TOKEN,
      error: null,
      warning: null,
      target: 'booth',
    });
    expect(readTokenInput(`https://party.example/?t=${TOKEN}&debug=1`, ctx).target).toBe('');
    expect(readTokenInput(`party.example/x/beer/?t=${TOKEN}`, ctx).target).toBe('beer');
    expect(readTokenInput(`/x/booth/?t=${TOKEN}`, ctx)).toMatchObject({ token: TOKEN, target: 'booth' });
    // an activity that is not loaded here: the target stays as it is
    expect(readTokenInput(`https://party.example/x/wall/?t=${TOKEN}`, ctx).target).toBeNull();
  });

  it('says when a link has no token, or one the server would refuse', () => {
    expect(readTokenInput('https://party.example/x/booth/', ctx)).toEqual({
      token: null,
      error: NO_TOKEN_IN_LINK,
      warning: null,
      target: null,
    });
    expect(readTokenInput('https://party.example/?t=', ctx).error).toBe(NO_TOKEN_IN_LINK);
    expect(readTokenInput('https://party.example/?t=abababababababab', ctx).error).toBe(TOKEN_TOO_SIMPLE);
    expect(readTokenInput('mailto:someone?t=abc', ctx).error).not.toBeNull();
  });

  it('warns (without blocking) when the link points at another host', () => {
    const read = readTokenInput(`https://old-party.example:8443/?t=${TOKEN}`, ctx);
    expect(read.error).toBeNull();
    expect(read.token).toBe(TOKEN);
    expect(read.warning).toBe(
      'Achtung: Der Link zeigt auf old-party.example:8443, die Party läuft auf party.example. Der Code funktioniert nur, wenn er auf diese Adresse zeigt.',
    );
    expect(readTokenInput(`https://PARTY.example/?t=${TOKEN}`, ctx).warning).toBeNull();
  });

  it('reads targets from paths', () => {
    expect(targetOfPath('/', activities)).toBe('');
    expect(targetOfPath('/x/booth/', activities)).toBe('booth');
    expect(targetOfPath('/x/booth', activities)).toBe('booth');
    expect(targetOfPath('/x/nope/', activities)).toBeNull();
    expect(targetOfPath('/admin', activities)).toBeNull();
  });
});

describe('texts', () => {
  it('names targets', () => {
    expect(targetLabel('', activities)).toBe('Start');
    expect(targetLabel('booth', activities)).toBe('Fotobox');
    expect(targetLabel('wall', activities)).toBe('Ziel nicht verfügbar');
    expect(targetFromLinkNote('booth', activities)).toBe('Ziel auf „Fotobox“ gesetzt, wie im Link.');
  });

  it('counts codes', () => {
    expect(countText(3, 1)).toBe('3 aktiv · 1 gelöscht');
    expect(countText(3, 0)).toBe('3 aktiv');
    expect(countText(0, 2)).toBe('0 aktiv · 2 gelöscht');
  });

  it('says when a code was revoked', () => {
    const at = new Date(2026, 9, 13, 22, 41).toISOString();
    expect(revokedTitle(at)).toBe('gelöscht am 13.10., 22:41');
  });

  it('says how often a code was scanned', () => {
    expect(scansText(12, 9)).toBe('12-mal von 9 Personen');
    expect(scansText(1, 1)).toBe('1-mal von 1 Person');
    expect(scansText(0, 0)).toBe('Noch nie');
  });
});
