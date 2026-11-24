import { zodResolver } from "@hookform/resolvers/zod";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, Building2, KeyRound } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { OtpInput } from "../components/OtpInput";
import { Shell } from "../components/Shell";
import { Alert, Button, TextField } from "../components/ui";
import { AuthApiError, authApi, workbenchUrl } from "../lib/api";

const schema = z.object({
  email: z.string().min(1, "Enter your work email").email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
type Form = z.infer<typeof schema>;
type MfaState = { token: string; enroll?: { uri: string; secret: string } };

export function LoginPage({ redirect = (u: string) => window.location.assign(u) }: { redirect?: (u: string) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [mfa, setMfa] = useState<MfaState | null>(null);
  const [code, setCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [sso, setSso] = useState(false);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema), mode: "onTouched" });

  useEffect(() => {
    authApi.config().then((c) => setSso(c.sso_enabled));
  }, []);

  const onSubmit = async (v: Form) => {
    setError(null);
    try {
      const r = await authApi.login(v.email, v.password);
      if (r.status === "authenticated") redirect(workbenchUrl());
      else if (r.status === "mfa_required") setMfa({ token: r.mfa_token });
      else setMfa({ token: r.mfa_token, enroll: { uri: r.otpauth_uri, secret: r.secret } });
    } catch (e) {
      const err = e as AuthApiError;
      setError(err.code === "account_locked" && err.retryAfter
        ? `Account temporarily locked. Try again in ${Math.ceil(err.retryAfter / 60)} minute(s).`
        : err.message);
    }
  };

  const verify = async (value: string) => {
    if (!mfa || verifying) return;
    setVerifying(true);
    setError(null);
    try {
      await authApi.verifyMfa(mfa.token, value);
      redirect(workbenchUrl());
    } catch (e) {
      setError((e as Error).message);
      setCode("");
    } finally {
      setVerifying(false);
    }
  };

  return (
    <Shell
      title={mfa ? (mfa.enroll ? "Set up two-step verification" : "Two-step verification") : "Sign in"}
      subtitle={mfa ? "Enter the 6-digit code from your authenticator app." : "Use your Northstar work account."}
    >
      <AnimatePresence mode="wait" initial={false}>
        {!mfa ? (
          <motion.form key="pwd" onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4"
            initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }}>
            {error && <Alert>{error}</Alert>}
            <TextField label="Work email" type="email" autoComplete="username" placeholder="name@northstar.example"
              error={formState.errors.email?.message} {...register("email")} />
            <TextField label="Password" type="password" autoComplete="current-password"
              error={formState.errors.password?.message} {...register("password")} />
            <div className="flex justify-end">
              <Link to="/forgot-password" className="text-sm font-medium text-brand-600 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500">
                Forgot password?
              </Link>
            </div>
            <Button type="submit" loading={formState.isSubmitting}>Sign in</Button>
            {sso && (
              <>
                <div className="flex items-center gap-3 text-xs text-ink-400"><span className="h-px flex-1 bg-ink-200 dark:bg-ink-700" />or<span className="h-px flex-1 bg-ink-200 dark:bg-ink-700" /></div>
                <Button type="button" variant="ghost" onClick={() => redirect("/auth/oidc/login")}>
                  <Building2 className="h-4 w-4" aria-hidden /> Continue with Microsoft (Azure AD)
                </Button>
              </>
            )}
          </motion.form>
        ) : (
          <motion.div key="mfa" className="space-y-5" initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }}>
            {error && <Alert>{error}</Alert>}
            {mfa.enroll && (
              <div className="rounded-xl border border-brand-100 bg-brand-50 p-3 text-sm text-ink-800 dark:border-ink-700 dark:bg-ink-900/50 dark:text-ink-200">
                <p className="flex items-center gap-2 font-medium"><KeyRound className="h-4 w-4" aria-hidden /> Add this key to your authenticator app</p>
                <code className="mt-2 block break-all rounded-lg bg-white px-2 py-1.5 font-mono text-xs dark:bg-ink-800" aria-label="Setup key">{mfa.enroll.secret}</code>
              </div>
            )}
            <OtpInput value={code} onChange={setCode} onComplete={verify} disabled={verifying} invalid={!!error} />
            <Button type="button" loading={verifying} disabled={code.length !== 6} onClick={() => verify(code)}>Verify</Button>
            <button type="button" onClick={() => { setMfa(null); setCode(""); setError(null); }}
              className="mx-auto flex items-center gap-1 text-sm text-ink-400 hover:text-ink-800 dark:hover:text-white">
              <ArrowLeft className="h-4 w-4" aria-hidden /> Use a different account
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </Shell>
  );
}
