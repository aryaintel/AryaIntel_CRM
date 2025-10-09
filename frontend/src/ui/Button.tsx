import React from "react";
import { cn } from "./cn";

type Tone = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md";

const base =
  "inline-flex items-center justify-center font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1";
const sizes: Record<Size, string> = {
  sm: "text-sm px-2.5 py-1.5",
  md: "text-sm px-3 py-2",
};
const tones: Record<Tone, string> = {
  primary:
    "bg-indigo-600 text-white hover:bg-indigo-700 focus:ring-indigo-500/30 border border-indigo-600",
  secondary:
    "border text-gray-800 hover:bg-gray-50 bg-white focus:ring-gray-400/30",
  danger:
    "border border-rose-600 text-rose-700 hover:bg-rose-50 bg-white focus:ring-rose-500/30",
  ghost:
    "text-gray-700 hover:bg-gray-50",
};

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: Tone;
  size?: Size;
};

export function Button({ tone = "primary", size = "md", className, ...props }: Props) {
  return (
    <button
      {...props}
      className={cn(base, sizes[size], tones[tone], "disabled:opacity-50", className)}
    />
  );
}
