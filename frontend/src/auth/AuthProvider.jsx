import { useQueryClient } from "@tanstack/react-query";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getRedirectResult,
  onAuthStateChanged,
  reload,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  signOut as firebaseSignOut,
  updateProfile,
} from "firebase/auth";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { configureAuth } from "@/api/client";
import { auth, firebaseConfigured } from "./firebase";

const AuthContext = createContext(null);

function clearSessionStorage() {
  try {
    sessionStorage.clear();
  } catch {
    // Storage can be unavailable in private modes.
  }
}

/** A password account must confirm its email; Google accounts arrive confirmed. */
export function needsVerification(user) {
  if (!user || user.emailVerified) return false;
  return user.providerData.some((p) => p.providerId === "password");
}

export function AuthProvider({ children }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState(firebaseConfigured ? "loading" : "unconfigured");
  const [redirectError, setRedirectError] = useState(null);
  // Bumped when the user object changes in place (reload after verifying).
  const [version, setVersion] = useState(0);

  const signOut = useCallback(async () => {
    // Nothing from this account may be left for the next person on the device.
    queryClient.clear();
    clearSessionStorage();
    if (auth) await firebaseSignOut(auth);
  }, [queryClient]);

  const signInAsDemo = useCallback(
    async (account) => {
      if (auth.currentUser?.uid === account.uid) return;
      await signInWithEmailAndPassword(auth, account.email, account.password);
      // Switching straight from one account to another: drop what the last
      // one loaded, and refetch what is on screen as the new one.
      clearSessionStorage();
      await queryClient.resetQueries();
    },
    [queryClient],
  );

  useEffect(() => {
    if (!auth) return undefined;
    getRedirectResult(auth).catch(setRedirectError);
    return onAuthStateChanged(auth, (next) => {
      setUser(next);
      setStatus(next ? "signedIn" : "signedOut");
    });
  }, []);

  useEffect(() => {
    configureAuth({
      token: async (forceRefresh) => (auth?.currentUser ? auth.currentUser.getIdToken(forceRefresh) : null),
      signedOut: () => {
        signOut();
      },
    });
  }, [signOut]);

  const value = useMemo(() => {
    const google = new GoogleAuthProvider();
    google.setCustomParameters({ prompt: "select_account" });

    return {
      user,
      status,
      redirectError,
      signOut,
      signInAsDemo,
      async signInWithGoogle() {
        const narrow = window.matchMedia("(max-width: 640px)").matches;
        if (narrow) return signInWithRedirect(auth, google);
        try {
          return await signInWithPopup(auth, google);
        } catch (error) {
          if (error.code === "auth/popup-blocked") return signInWithRedirect(auth, google);
          throw error;
        }
      },
      signInWithEmail(email, password) {
        return signInWithEmailAndPassword(auth, email, password);
      },
      async signUpWithEmail({ name, email, password }) {
        const credential = await createUserWithEmailAndPassword(auth, email, password);
        if (name) await updateProfile(credential.user, { displayName: name });
        await sendEmailVerification(credential.user);
        return credential;
      },
      resendVerification() {
        return sendEmailVerification(auth.currentUser);
      },
      async refreshVerification() {
        await reload(auth.currentUser);
        // The backend reads email_verified from the token, so mint a new one.
        await auth.currentUser.getIdToken(true);
        setVersion((v) => v + 1);
        return auth.currentUser.emailVerified;
      },
      resetPassword(email) {
        return sendPasswordResetEmail(auth, email);
      },
    };
    // version: the user object changes in place when it is reloaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, status, redirectError, signOut, signInAsDemo, version]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
