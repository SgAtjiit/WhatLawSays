// Firebase error codes, said the way a person would want to hear them.
const MESSAGES = {
  "auth/invalid-credential": "That email and password don't match. Try again, or reset your password.",
  "auth/wrong-password": "That email and password don't match. Try again, or reset your password.",
  "auth/user-not-found": "That email and password don't match. Try again, or reset your password.",
  "auth/invalid-email": "That doesn't look like an email address.",
  "auth/email-already-in-use": "There's already an account with this email. Sign in instead.",
  "auth/weak-password": "Use at least 8 characters for your password.",
  "auth/too-many-requests": "Too many attempts. Wait a few minutes, then try again.",
  "auth/network-request-failed": "Couldn't reach the sign-in service. Check your connection.",
  "auth/user-disabled": "This account has been disabled.",
  "auth/popup-blocked": "Your browser blocked the Google sign-in window.",
  "auth/account-exists-with-different-credential":
    "This email is already registered with a password. Sign in with your password instead.",
  "auth/operation-not-allowed": "This sign-in method isn't enabled for this app yet.",
  "auth/unauthorized-domain": "Sign-in isn't allowed from this address. Add it to the Firebase authorized domains.",
};

// Closing the Google window is a choice, not an error.
const SILENT = new Set(["auth/popup-closed-by-user", "auth/cancelled-popup-request"]);

export function authMessage(error) {
  if (!error) return null;
  if (SILENT.has(error.code)) return null;
  return MESSAGES[error.code] || "Something went wrong signing you in. Try again.";
}
