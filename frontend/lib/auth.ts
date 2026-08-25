// Admin auth: a username+password login against Cognito's `InitiateAuth`
// (USER_PASSWORD_AUTH), called directly from the browser — Cognito's
// identity-provider API is designed for exactly that, no AWS SigV4 signing
// or SDK needed, just a plain fetch with the right `X-Amz-Target` header.
// The resulting access token is held in the browser (localStorage) and
// sent as `Authorization: Bearer <token>` on every admin API call (see
// lib/api.ts). There is no sign-up flow anywhere in this app — the single
// admin user is created by hand in the Cognito console (see
// infra/stacks/auth_stack.py's docstring).
//
// `NEXT_PUBLIC_AUTH_STUB=1`: skip the real Cognito call entirely and check
// a fixed local username/password instead, minting the same stub bearer
// token the backend's AUTH_STUB accepts (see backend/app/core/auth.py).
// Only ever set for local dev / the E2E suite (docker-compose.e2e.yml) —
// LocalStack Community doesn't include Cognito, so there's nothing real to
// call there.
//
// Guarded with `typeof window` checks (not just try/catch) because this
// module is imported from "use client" components that still get
// statically rendered to HTML at `next build` time (output: 'export') —
// there's no `window` in that Node.js build step, only in the browser
// afterward.

const STORAGE_KEY = "backecast_admin_token";

const AUTH_STUB = process.env.NEXT_PUBLIC_AUTH_STUB === "1";
const COGNITO_REGION = process.env.NEXT_PUBLIC_COGNITO_REGION ?? "sa-east-1";
const COGNITO_CLIENT_ID = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? "";

const STUB_USERNAME = "admin";
const STUB_PASSWORD = "local-dev-admin-password";
const STUB_TOKEN = "local-dev-admin-token";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Storage blocked (private browsing, quota, etc.) — the token just
    // won't persist across reloads; not worth surfacing as an error.
  }
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

// Returns a Cognito access token, or throws an Error with a message safe
// to show the user directly.
export async function login(username: string, password: string): Promise<string> {
  if (AUTH_STUB) {
    if (username !== STUB_USERNAME || password !== STUB_PASSWORD) {
      throw new Error("Invalid username or password.");
    }
    return STUB_TOKEN;
  }

  const response = await fetch(`https://cognito-idp.${COGNITO_REGION}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
    },
    body: JSON.stringify({
      AuthFlow: "USER_PASSWORD_AUTH",
      ClientId: COGNITO_CLIENT_ID,
      AuthParameters: { USERNAME: username, PASSWORD: password },
    }),
  });

  if (!response.ok) {
    throw new Error("Invalid username or password.");
  }

  const body = await response.json();
  const accessToken = body?.AuthenticationResult?.AccessToken;
  if (typeof accessToken !== "string") {
    throw new Error("Login failed — unexpected response from Cognito.");
  }
  return accessToken;
}
