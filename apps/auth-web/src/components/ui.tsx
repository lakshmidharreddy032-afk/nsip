import { AlertCircle, Eye, EyeOff, Loader2 } from "lucide-react";
import clsx from "clsx";
import { forwardRef, useId, useState, type InputHTMLAttributes, type ReactNode, type ButtonHTMLAttributes } from "react";

export function Brand() {
  return (
    <div className="flex items-center gap-3">
      <svg aria-hidden viewBox="0 0 32 32" className="h-9 w-9">
        <defs>
          <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#8fb0ff" />
            <stop offset="1" stopColor="#3a63e6" />
          </linearGradient>
        </defs>
        <path d="M16 2l3.5 10.5L30 16l-10.5 3.5L16 30l-3.5-10.5L2 16l10.5-3.5z" fill="url(#g)" />
      </svg>
      <div className="leading-tight">
        <div className="text-base font-semibold tracking-tight text-ink-900 dark:text-white">Northstar General</div>
        <div className="text-xs text-ink-400">Submission Intelligence Platform</div>
      </div>
    </div>
  );
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: ReactNode };

export const TextField = forwardRef<HTMLInputElement, FieldProps>(function TextField({ label, error, hint, type, className, ...rest }, ref) {
  const id = useId();
  const [show, setShow] = useState(false);
  const isPassword = type === "password";
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink-800 dark:text-ink-200">
        {label}
      </label>
      <div className="relative">
        <input
          ref={ref}
          id={id}
          type={isPassword && show ? "text" : type}
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-err` : undefined}
          className={clsx(
            "w-full rounded-xl border bg-white/80 px-3.5 py-2.5 text-sm text-ink-900 shadow-sm outline-none transition",
            "placeholder:text-ink-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-500/15 dark:bg-ink-800/70 dark:text-white",
            error ? "border-red-400" : "border-ink-200 dark:border-ink-700",
            isPassword && "pr-11",
          )}
          {...rest}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-xl text-ink-400 hover:text-ink-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500 dark:hover:text-white"
            aria-label={show ? "Hide password" : "Show password"}
            aria-pressed={show}
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        )}
      </div>
      {error ? (
        <p id={`${id}-err`} role="alert" className="mt-1.5 text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : (
        hint && <p className="mt-1.5 text-xs text-ink-400">{hint}</p>
      )}
    </div>
  );
});

export function Button({ loading, children, variant = "primary", className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; variant?: "primary" | "ghost" }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        "inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary"
          ? "bg-brand-600 text-white shadow-lg shadow-brand-600/25 hover:bg-brand-700"
          : "border border-ink-200 bg-white/70 text-ink-800 hover:bg-white dark:border-ink-700 dark:bg-ink-800/60 dark:text-ink-200",
        className,
      )}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Alert({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="flex animate-shake items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 motion-reduce:animate-none dark:border-red-900 dark:bg-red-950/50 dark:text-red-300">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span>{children}</span>
    </div>
  );
}
