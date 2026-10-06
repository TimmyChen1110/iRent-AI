"use client";

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success" | "warning";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: React.ReactNode;
  block?: boolean;
}

const variants: Record<Variant, string> = {
  primary:
    "bg-white text-black hover:bg-white/90 shadow-[0_10px_30px_-12px_color-mix(in_srgb,var(--color-white)_40%,transparent)]",
  secondary:
    "bg-white/[0.06] text-white/90 hover:bg-white/[0.1] border border-white/[0.08]",
  ghost: "text-white/70 hover:text-white hover:bg-white/[0.06]",
  danger:
    "bg-rose-500/15 text-rose-200 hover:bg-rose-500/25 border border-rose-400/20",
  success:
    "bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25 border border-emerald-400/20",
  warning:
    "bg-amber-500/15 text-amber-200 hover:bg-amber-500/25 border border-amber-400/20",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-lg",
  md: "h-9.5 px-3.5 text-[13px] gap-2 rounded-xl",
  lg: "h-11 px-5 text-sm gap-2 rounded-xl",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, block, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap font-medium transition-all duration-200 active:scale-[0.98] disabled:opacity-40 disabled:pointer-events-none focus:outline-none focus-visible:ring-2 focus-visible:ring-white/30",
        variants[variant],
        sizes[size],
        block && "w-full",
        className,
      )}
      {...rest}
    >
      {icon && <span className="shrink-0 [&>svg]:h-4 [&>svg]:w-4">{icon}</span>}
      {children}
    </button>
  );
});
