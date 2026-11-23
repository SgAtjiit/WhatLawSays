import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router";

import { useAuth } from "@/auth/AuthProvider";
import { demoAccount } from "@/auth/demo";
import { authMessage } from "@/auth/messages";
import { safeNext } from "@/auth/RequireAuth";
import { Splash } from "@/components/Splash";
import { NotFound } from "@/routes/NotFound";

// StrictMode runs the effect twice in development; both runs share one sign-in.
const pending = new Map();
function signInOnce(account, signIn) {
  if (!pending.has(account.id)) {
    pending.set(account.id, signIn(account).finally(() => pending.delete(account.id)));
  }
  return pending.get(account.id);
}

/** /demo/:id signs in as that demo account, then goes to ?next= or to its reviews. */
export function DemoSignIn() {
  const { id } = useParams();
  const account = demoAccount(id);
  const { status, signInAsDemo } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState(null);
  const ready = status !== "loading";
  const target = new URLSearchParams(location.search).has("next") ? safeNext(location.search) : "/reviews";

  useEffect(() => {
    if (!account || !ready) return undefined;
    let live = true;
    signInOnce(account, signInAsDemo).then(
      () => live && navigate(target, { replace: true }),
      (failure) => live && setError(authMessage(failure)),
    );
    return () => {
      live = false;
    };
  }, [account, ready, signInAsDemo, navigate, target]);

  if (!account) return <NotFound />;
  if (error) {
    return (
      <NotFound title={`Couldn't sign in as ${account.name}`}>
        <p>{error}</p>
        <p className="mt-2">
          The demo accounts are created when <code className="font-mono text-ink">./demo.sh</code> starts. Is it
          still running?
        </p>
      </NotFound>
    );
  }
  return <Splash />;
}
