import { Notice } from "./common";

export function SetupNeeded() {
  return (
    <div className="mx-auto max-w-xl px-4 py-16">
      <Notice tone="warning" title="Sign-in isn't set up yet">
        <p>
          This copy of WhatLawSays has no Firebase configuration. Copy{" "}
          <code className="font-mono text-xs">frontend/.env.example</code> to{" "}
          <code className="font-mono text-xs">frontend/.env.local</code>, fill in your Firebase web app's
          settings, and restart the dev server. For local testing, set{" "}
          <code className="font-mono text-xs">VITE_FIREBASE_AUTH_EMULATOR</code> and run{" "}
          <code className="font-mono text-xs">npm run emulator</code>.
        </p>
      </Notice>
    </div>
  );
}
