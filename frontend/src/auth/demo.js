import spec from "./demo-accounts.json";

// Demo sign-in exists only against the local Auth emulator. Its password is
// in this bundle, so it must never be able to open an account in a real
// Firebase project; outside demo mode the accounts are dropped from the build.
// (Read import.meta.env directly: Vite replaces it at build time, which is
// what lets the accounts below be removed as dead code.)
export const DEMO_ENABLED =
  import.meta.env.VITE_DEMO === "true" && Boolean(import.meta.env.VITE_FIREBASE_AUTH_EMULATOR);

export const DEMO_ACCOUNTS = DEMO_ENABLED
  ? spec.accounts.map((account) => ({
      id: account.id,
      uid: account.uid,
      name: account.name,
      email: account.email,
      blurb: account.blurb,
      password: spec.password,
    }))
  : [];

export function demoAccount(id) {
  return DEMO_ACCOUNTS.find((account) => account.id === id) ?? null;
}

export function demoAccountFor(user) {
  return user ? (DEMO_ACCOUNTS.find((account) => account.uid === user.uid) ?? null) : null;
}

/** The link that signs in as a demo account and comes back to `next`. */
export function demoHref(account, next) {
  return next ? `/demo/${account.id}?next=${encodeURIComponent(next)}` : `/demo/${account.id}`;
}
