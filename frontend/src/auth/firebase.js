import { initializeApp } from "firebase/app";
import { connectAuthEmulator, getAuth } from "firebase/auth";

const env = import.meta.env;

const config = {
  apiKey: env.VITE_FIREBASE_API_KEY,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: env.VITE_FIREBASE_PROJECT_ID,
  appId: env.VITE_FIREBASE_APP_ID,
};

const emulator = env.VITE_FIREBASE_AUTH_EMULATOR;

// The emulator accepts any key; a real project needs the full web config.
export const firebaseConfigured = Boolean(
  config.projectId && (emulator || (config.apiKey && config.authDomain && config.appId)),
);

export const auth = (() => {
  if (!firebaseConfigured) return null;
  const app = initializeApp(emulator ? { ...config, apiKey: config.apiKey || "emulator" } : config);
  const instance = getAuth(app);
  if (emulator) connectAuthEmulator(instance, emulator, { disableWarnings: true });
  return instance;
})();
