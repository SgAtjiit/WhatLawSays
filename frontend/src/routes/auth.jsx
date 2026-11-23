import { Loader2, MailCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";

import { needsVerification, useAuth } from "@/auth/AuthProvider";
import { authMessage } from "@/auth/messages";
import { DEMO_ENABLED } from "@/auth/demo";
import { safeNext } from "@/auth/RequireAuth";
import { DemoAccountList } from "@/components/Demo";
import { Notice } from "@/components/common";
import { SetupNeeded } from "@/components/SetupNeeded";
import { Splash } from "@/components/Splash";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function AuthLayout({ title, lead, children, footer }) {
  return (
    <div className="mx-auto w-full max-w-[26rem] px-4 py-14 sm:py-20">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {lead && <p className="mt-2 text-graphite">{lead}</p>}
      <div className="mt-8">{children}</div>
      {footer && <div className="mt-8 border-t border-rule pt-6 text-graphite">{footer}</div>}
    </div>
  );
}

function GoogleMark() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-[18px]">
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.5 5.5 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 7.9-2.9l-3.9-3c-1.1.7-2.4 1.2-4 1.2-3.1 0-5.7-2.1-6.6-4.9H1.4v3.1A12 12 0 0 0 12 24z" />
      <path fill="#FBBC05" d="M5.4 14.4a7.2 7.2 0 0 1 0-4.7V6.6h-4a12 12 0 0 0 0 10.8l4-3z" />
      <path fill="#EA4335" d="M12 4.8c1.7 0 3.3.6 4.5 1.8l3.4-3.4A12 12 0 0 0 1.4 6.6l4 3.1C6.3 6.9 8.9 4.8 12 4.8z" />
    </svg>
  );
}

function GoogleButton({ onError }) {
  const { signInWithGoogle } = useAuth();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      type="button"
      variant="outline"
      size="lg"
      className="w-full"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        onError(null);
        try {
          await signInWithGoogle();
        } catch (error) {
          onError(authMessage(error));
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? <Loader2 aria-hidden className="animate-spin" /> : <GoogleMark />}
      Continue with Google
    </Button>
  );
}

function Divider({ children = "or with email" }) {
  return (
    <div className="my-6 flex items-center gap-3 text-xs text-graphite">
      <span className="h-px flex-1 bg-rule" />
      {children}
      <span className="h-px flex-1 bg-rule" />
    </div>
  );
}

function Field({ id, label, hint, ...props }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-[0.9375rem] font-medium">
        {label}
      </Label>
      <Input id={id} name={id} className="h-11 bg-sheet text-base" aria-describedby={hint ? `${id}-hint` : undefined} {...props} />
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-graphite">
          {hint}
        </p>
      )}
    </div>
  );
}

/** Signed-in visitors to an auth screen go where they were heading. */
function useSignedInRedirect() {
  const { user, status } = useAuth();
  const location = useLocation();
  if (status === "unconfigured") return <SetupNeeded />;
  if (status === "loading") return <Splash />;
  if (user && needsVerification(user)) return <Navigate to={`/verify-email${location.search}`} replace />;
  if (user) return <Navigate to={safeNext(location.search)} replace />;
  return null;
}

export function SignIn() {
  const { signInWithEmail, redirectError } = useAuth();
  const location = useLocation();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const redirect = useSignedInRedirect();

  if (redirect) return redirect;
  const shown = error ?? authMessage(redirectError);

  return (
    <AuthLayout
      title="Sign in"
      lead="Your contracts and reviews are private to your account."
      footer={
        <p>
          New here?{" "}
          <Link className="text-seal underline underline-offset-4" to={`/sign-up${location.search}`}>
            Create an account
          </Link>
        </p>
      }
    >
      {shown && <Notice tone="danger" className="mb-6">{shown}</Notice>}
      {DEMO_ENABLED && (
        <>
          <DemoAccountList next={new URLSearchParams(location.search).get("next") ?? undefined} />
          <Divider>or with your own account</Divider>
        </>
      )}
      <GoogleButton onError={setError} />
      <Divider />
      <form
        className="space-y-5"
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError(null);
          try {
            await signInWithEmail(form.get("email"), form.get("password"));
          } catch (failure) {
            setError(authMessage(failure));
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field id="email" label="Email" type="email" autoComplete="email" required />
        <div className="space-y-1.5">
          <Field id="password" label="Password" type="password" autoComplete="current-password" required />
          <Link to="/reset-password" className="inline-block text-xs text-seal underline underline-offset-4">
            Forgot your password?
          </Link>
        </div>
        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          {busy && <Loader2 aria-hidden className="animate-spin" />}
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}

export function SignUp() {
  const { signUpWithEmail } = useAuth();
  const location = useLocation();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const redirect = useSignedInRedirect();
  if (redirect) return redirect;

  return (
    <AuthLayout
      title="Create an account"
      lead="So your contracts stay yours: nobody else can open a review you upload."
      footer={
        <p>
          Already have an account?{" "}
          <Link className="text-seal underline underline-offset-4" to={`/sign-in${location.search}`}>
            Sign in
          </Link>
        </p>
      }
    >
      {error && <Notice tone="danger" className="mb-6">{error}</Notice>}
      <GoogleButton onError={setError} />
      <Divider />
      <form
        className="space-y-5"
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const password = String(form.get("password"));
          if (password.length < 8) {
            setError("Use at least 8 characters for your password.");
            return;
          }
          setBusy(true);
          setError(null);
          try {
            await signUpWithEmail({
              name: String(form.get("name") || "").trim(),
              email: form.get("email"),
              password,
            });
          } catch (failure) {
            setError(authMessage(failure));
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field id="name" label="Your name" autoComplete="name" hint="Optional." />
        <Field id="email" label="Email" type="email" autoComplete="email" required />
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          required
          hint="At least 8 characters."
        />
        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          {busy && <Loader2 aria-hidden className="animate-spin" />}
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}

const RESEND_COOLDOWN = 60;

export function VerifyEmail() {
  const { user, status, resendVerification, refreshVerification, signOut } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [cooldown, setCooldown] = useState(0);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (!cooldown) return undefined;
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  if (status === "unconfigured") return <SetupNeeded />;
  if (status === "loading") return <Splash />;
  if (!user) return <Navigate to={`/sign-in${location.search}`} replace />;
  if (!needsVerification(user)) return <Navigate to={safeNext(location.search)} replace />;

  return (
    <AuthLayout
      title="Check your inbox"
      lead={
        <>
          We sent a link to <span className="font-medium text-ink">{user.email}</span>. Open it to confirm this
          is your address, then come back here.
        </>
      }
      footer={
        <p>
          Wrong address?{" "}
          <button
            type="button"
            className="cursor-pointer text-seal underline underline-offset-4"
            onClick={async () => {
              await signOut();
              navigate("/sign-up");
            }}
          >
            Start again with another email
          </button>
        </p>
      }
    >
      <MailCheck aria-hidden className="mb-6 size-10 text-seal" strokeWidth={1.5} />
      {message && <Notice className="mb-5">{message}</Notice>}
      {error && <Notice tone="danger" className="mb-5">{error}</Notice>}
      <div className="flex flex-col gap-3">
        <Button
          size="lg"
          className="w-full"
          disabled={checking}
          onClick={async () => {
            setChecking(true);
            setError(null);
            try {
              const verified = await refreshVerification();
              if (verified) navigate(safeNext(location.search), { replace: true });
              else setMessage("Not confirmed yet. Open the link in the email, then try again.");
            } catch (failure) {
              setError(authMessage(failure));
            } finally {
              setChecking(false);
            }
          }}
        >
          {checking && <Loader2 aria-hidden className="animate-spin" />}
          I've confirmed my email
        </Button>
        <Button
          variant="outline"
          size="lg"
          className="w-full"
          disabled={cooldown > 0}
          onClick={async () => {
            setError(null);
            try {
              await resendVerification();
              setMessage("Sent again. It can take a minute; check your spam folder too.");
              setCooldown(RESEND_COOLDOWN);
            } catch (failure) {
              setError(authMessage(failure));
            }
          }}
        >
          {cooldown > 0 ? `Resend in ${cooldown} s` : "Resend the email"}
        </Button>
      </div>
    </AuthLayout>
  );
}

export function ResetPassword() {
  const { resetPassword, status } = useAuth();
  const [sentTo, setSentTo] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  if (status === "unconfigured") return <SetupNeeded />;

  return (
    <AuthLayout
      title="Reset your password"
      lead="Enter the email you signed up with and we'll send a link to choose a new password."
      footer={
        <Link className="text-seal underline underline-offset-4" to="/sign-in">
          Back to sign in
        </Link>
      }
    >
      {sentTo ? (
        <Notice title="Check your inbox">
          If an account exists for {sentTo}, a reset link is on its way. It can take a minute.
        </Notice>
      ) : (
        <form
          className="space-y-5"
          onSubmit={async (event) => {
            event.preventDefault();
            const email = String(new FormData(event.currentTarget).get("email"));
            setBusy(true);
            setError(null);
            try {
              await resetPassword(email);
              setSentTo(email);
            } catch (failure) {
              // Saying whether an account exists would let anyone probe for one.
              if (failure.code === "auth/user-not-found") setSentTo(email);
              else setError(authMessage(failure));
            } finally {
              setBusy(false);
            }
          }}
        >
          {error && <Notice tone="danger">{error}</Notice>}
          <Field id="email" label="Email" type="email" autoComplete="email" required />
          <Button type="submit" size="lg" className="w-full" disabled={busy}>
            {busy && <Loader2 aria-hidden className="animate-spin" />}
            Send reset link
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
