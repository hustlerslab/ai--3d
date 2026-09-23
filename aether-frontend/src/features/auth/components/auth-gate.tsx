"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/shared/button";

import { AuthError, type AuthUser, currentUser, register, signIn, signOut } from "../api/auth-api";

/**
 * Sign-in, and the shell around it.
 *
 * P0-SEC-002 closed 60 of the 63 API routes. Without this the product still
 * runs but nobody can use it: every call returns 401 and the studio shows a
 * network error it cannot explain. Auth is not a feature bolted on beside the
 * studio — it is what makes the studio reachable at all.
 *
 * Three states, and the first is the one usually got wrong:
 *   1. checking   — a brief, quiet "is anyone signed in?"
 *   2. signed out — the form
 *   3. signed in  — the studio, plus a way back out
 *
 * State 1 renders as calm text rather than a spinner or a flash of the form.
 * Showing "Sign in" for 200ms to somebody who *is* signed in reads as being
 * logged out, and people re-enter passwords they never needed to.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    currentUser(controller.signal)
      .then(setUser)
      .finally(() => setChecking(false));
    return () => controller.abort();
  }, []);

  const onSignOut = useCallback(async () => {
    await signOut();
    setUser(null);
  }, []);

  if (checking) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="body-sm text-ink-muted">Checking your session…</p>
      </div>
    );
  }

  if (!user) return <SignInForm onSignedIn={setUser} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <span className="body-sm text-ink-muted">
          Signed in as <span className="text-ink-soft">{user.email}</span>
          {user.role !== "homeowner" ? ` · ${user.role}` : ""}
        </span>
        <Button variant="ghost" size="sm" onClick={onSignOut}>
          Sign out
        </Button>
      </div>
      {children}
    </div>
  );
}

function SignInForm({ onSignedIn }: { onSignedIn: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<"signin" | "register">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await (mode === "signin" ? signIn : register)(email, password));
    } catch (err) {
      // Show the server's own words. It has already decided how much to
      // reveal — "Email or password is incorrect" is deliberately vague so it
      // cannot be used to discover which accounts exist, and paraphrasing it
      // here would either leak more or say less.
      setError(err instanceof AuthError ? err.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const fieldClass =
    "rounded-md border border-tan bg-white px-3 py-2 body-sm text-ink-soft outline-none focus:border-ink-muted focus:ring-2 focus:ring-gold/40";

  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4">
      <form
        onSubmit={submit}
        className="flex w-full max-w-sm flex-col gap-5 rounded-lg border border-tan bg-sand/20 p-6"
      >
        <div className="flex flex-col gap-1">
          <h1 className="body font-medium text-ink-soft">
            {mode === "signin" ? "Sign in to Allure" : "Create your account"}
          </h1>
          <p className="body-sm text-ink-muted">
            Your projects, photographs and designs are visible only to you.
          </p>
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="caption text-ink-muted">Email</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className={fieldClass}
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="caption text-ink-muted">Password</span>
          <input
            type="password"
            required
            minLength={10}
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={fieldClass}
          />
          {mode === "register" ? (
            <span className="caption text-ink-muted">At least 10 characters.</span>
          ) : null}
        </label>

        {error ? (
          <p role="alert" className="body-sm text-danger">
            {error}
          </p>
        ) : null}

        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Working…" : mode === "signin" ? "Sign in" : "Create account"}
        </Button>

        <button
          type="button"
          onClick={() => {
            setMode(mode === "signin" ? "register" : "signin");
            setError(null);
          }}
          className="caption text-ink-muted underline-offset-2 hover:text-ink-soft hover:underline"
        >
          {mode === "signin"
            ? "No account yet? Create one"
            : "Already have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
