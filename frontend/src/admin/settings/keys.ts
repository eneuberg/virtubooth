/**
 * Query keys of the Einstellungen section. Under ['admin', …] like every admin key, so
 * a `stream.resync` refetches them too.
 */

/** GET /api/admin/settings: the event name and the password state */
export const settingsKey = ['admin', 'settings'] as const;

/** An extension's admin settings (GET /api/admin/x/<id>/…), refetched on `extension.settings` */
export const extensionSettingsKey = (id: string) => ['admin', 'x', id] as const;
