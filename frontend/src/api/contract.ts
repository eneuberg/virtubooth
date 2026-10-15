/**
 * Helpers for compile-time contract checks of hand-written API types against the
 * generated schema (admin/ml/contract.ts, wall/api/contract.ts). Types only.
 */

/** The answer as it arrives: optional (defaulted) fields are always there. */
export type Sent<T> = T extends readonly unknown[]
  ? { -readonly [K in keyof T]: Sent<T[K]> } // arrays and tuples stay what they are
  : T extends object
    ? { [K in keyof T]-?: Sent<Exclude<T[K], undefined>> }
    : T;

/**
 * Checked field by field: on deep types (Sent of Sent of …) a conditional type gives
 * up and answers false where plain assignability holds.
 */
export type Fits<Server, Ui> = false extends {
  [K in keyof Ui]-?: K extends keyof Server
    ? Sent<Exclude<Server[K], undefined>> extends Ui[K]
      ? true
      : false
    : false;
}[keyof Ui]
  ? false
  : true;
export type Assert<T extends true> = T;
