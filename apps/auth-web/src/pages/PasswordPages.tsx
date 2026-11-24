import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { Shell } from "../components/Shell";
import { Alert, Button, TextField } from "../components/ui";
import { authApi, passwordProblems } from "../lib/api";

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<{ email: string }>({
    resolver: zodResolver(z.object({ email: z.string().email("Enter a valid email address") })),
  });
  const onSubmit = async (v: { email: string }) => {
    setError(null);
    try {
      await authApi.forgot(v.email);
      setSent(true);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Shell title="Reset your password" subtitle="We will email a single-use link that expires in 30 minutes.">
      {sent ? (
        <div className="space-y-4" role="status">
          <p className="flex items-start gap-2 text-sm text-ink-800 dark:text-ink-200">
            <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" aria-hidden />
            If an account exists for that address, a reset link is on its way.
          </p>
          <Link to="/" className="block text-center text-sm font-medium text-brand-600 hover:underline">Back to sign in</Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          {error && <Alert>{error}</Alert>}
          <TextField label="Work email" type="email" autoComplete="username" error={formState.errors.email?.message} {...register("email")} />
          <Button type="submit" loading={formState.isSubmitting}>Send reset link</Button>
          <Link to="/" className="block text-center text-sm text-ink-400 hover:text-ink-800">Back to sign in</Link>
        </form>
      )}
    </Shell>
  );
}

const resetSchema = z.object({ password: z.string(), confirm: z.string() })
  .superRefine((v, ctx) => {
    const p = passwordProblems(v.password);
    if (p.length) ctx.addIssue({ code: "custom", path: ["password"], message: p.join(". ") });
    if (v.password !== v.confirm) ctx.addIssue({ code: "custom", path: ["confirm"], message: "Passwords do not match" });
  });

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<z.infer<typeof resetSchema>>({ resolver: zodResolver(resetSchema), mode: "onTouched" });
  const onSubmit = async (v: { password: string }) => {
    setError(null);
    try {
      await authApi.reset(token, v.password);
      setDone(true);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  if (!token) return <Shell title="Invalid link"><Alert>This reset link is missing its token.</Alert></Shell>;
  return (
    <Shell title="Choose a new password" subtitle="All your sessions will be signed out.">
      {done ? (
        <div role="status" className="space-y-4">
          <p className="text-sm text-ink-800 dark:text-ink-200">Your password has been updated.</p>
          <Link to="/" className="block text-center text-sm font-medium text-brand-600 hover:underline">Sign in</Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          {error && <Alert>{error}</Alert>}
          <TextField label="New password" type="password" autoComplete="new-password" hint="12+ characters, three character types"
            error={formState.errors.password?.message} {...register("password")} />
          <TextField label="Confirm password" type="password" autoComplete="new-password" error={formState.errors.confirm?.message} {...register("confirm")} />
          <Button type="submit" loading={formState.isSubmitting}>Update password</Button>
        </form>
      )}
    </Shell>
  );
}
