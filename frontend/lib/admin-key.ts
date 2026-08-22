// Where the admin key lives client-side, once entered on the /admin login
// gate. No real auth system — per manual.md's Phase 6 spec this is
// intentionally simple: a shared secret typed once, held in the browser,
// and sent as the X-Admin-Key header on every admin API call. Guarded with
// `typeof window` checks (not just try/catch) because this module is
// imported from "use client" components that still get statically
// rendered to HTML at `next build` time (output: 'export') — there's no
// `window` in that Node.js build step, only in the browser afterward.

const STORAGE_KEY = "backecast_admin_key";

export function getStoredAdminKey(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredAdminKey(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, key);
  } catch {
    // Storage blocked (private browsing, quota, etc.) — the key just
    // won't persist across reloads; not worth surfacing as an error.
  }
}

export function clearStoredAdminKey(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
