// Admin auth: the single admin signs in through Citadel (Igor's Cognito SSO hub) with the OAuth code flow + PKCE, done
// in the browser by oidc-client-ts. The access token is sent as `Authorization: Bearer <token>` on every admin API
// call (see lib/api.ts); the backend verifies it against the Citadel pool (backend/app/core/auth.py). Public pages
// never touch this module's network calls.
//
// Tokens live in sessionStorage, not localStorage: GitHub Pages serves every project of the account from one origin
// (igormcsouza.github.io), so localStorage would be readable by every other site under it. The cost is one silent
// re-login per new tab (Citadel's own session cookie makes that instant).
//
// `NEXT_PUBLIC_AUTH_STUB=1`: skip Citadel and check a fixed local username/password, minting the stub bearer token
// the backend's AUTH_STUB accepts. Only for local dev and the E2E suite (docker-compose.e2e.yml) - never a real deploy.
//
// Guarded with `typeof window` checks because "use client" components still get statically rendered at `next build`.

import { UserManager, WebStorageStateStore } from "oidc-client-ts";

const STORAGE_KEY = "backecast_admin_token";

const AUTH_STUB = process.env.NEXT_PUBLIC_AUTH_STUB === "1";
const AUTHORITY = process.env.NEXT_PUBLIC_OIDC_AUTHORITY ?? "";
const CLIENT_ID = process.env.NEXT_PUBLIC_OIDC_CLIENT_ID ?? "";
const HOSTED_UI = process.env.NEXT_PUBLIC_OIDC_HOSTED_UI ?? "";

const STUB_USERNAME = "admin";
const STUB_PASSWORD = "local-dev-admin-password";
const STUB_TOKEN = "local-dev-admin-token";

export const isStub = AUTH_STUB;

// The admin page itself is the OAuth callback (registered in Citadel's config/apps.json).
const adminUrl = () => `${location.origin}${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/admin`;

let manager: UserManager | undefined;
const oidc = () =>
  (manager ??= new UserManager({
    authority: AUTHORITY,
    client_id: CLIENT_ID,
    redirect_uri: adminUrl(),
    response_type: "code",
    scope: "openid",
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  }));

// The current access token, refreshed through the refresh token when it has expired; null when signed out.
export async function getStoredToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  try {
    if (AUTH_STUB) return window.localStorage.getItem(STORAGE_KEY);
    let user = await oidc().getUser();
    if (user?.expired) user = await oidc().signinSilent();
    return user?.access_token ?? null;
  } catch {
    return null;
  }
}

// Stub only: returns the stub token, or throws an Error whose message is safe to show.
export function stubLogin(username: string, password: string): string {
  if (username !== STUB_USERNAME || password !== STUB_PASSWORD) {
    throw new Error("Invalid username or password.");
  }
  window.localStorage.setItem(STORAGE_KEY, STUB_TOKEN);
  return STUB_TOKEN;
}

export function startLogin(): Promise<void> {
  return oidc().signinRedirect();
}

// Call on the admin page load: completes the code flow when Citadel just sent the browser back with `?code=`.
// Returns an error message to show, or null. Never redirects by itself, so an error cannot loop.
export async function finishLogin(): Promise<string | null> {
  if (AUTH_STUB) return null;
  const params = new URLSearchParams(location.search);
  if (params.has("error")) return params.get("error_description") ?? params.get("error");
  if (!params.has("code")) return null;
  try {
    await oidc().signinCallback();
  } catch {
    return "Sign in failed - please try again.";
  }
  history.replaceState(null, "", adminUrl());
  return null;
}

// Clears the local session AND Citadel's, otherwise the next sign-in would be instant.
export async function logout(): Promise<void> {
  if (AUTH_STUB) {
    window.localStorage.removeItem(STORAGE_KEY);
    return;
  }
  await oidc().removeUser();
  const query = new URLSearchParams({ client_id: CLIENT_ID, logout_uri: adminUrl() });
  location.replace(`${HOSTED_UI}/logout?${query}`);
}
