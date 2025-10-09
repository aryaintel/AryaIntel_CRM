import React from "react";
import { cn } from "./cn";

type Tone = "indigo" | "emerald" | "gray" | "rose";

const tones: Record<Tone, string> = {
  indigo: "bg-indigo-50 text-indigo-700 border-indigo-200",
  emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
  gray: "bg-gray-50 text-gray-700 border-gray-200",
  rose: "bg-rose-50 text-rose-700 border-rose-200",
};

export function Badge({
  tone = "gray",
  children,
  className,
}: React.PropsWithChildren<{ tone?: Tone; className?: string }>) {
  return (
    <span
      className={cn(
        "text-xs px-2 py-1 rounded-full border align-middle",
        tones[tone],
        className
      )}
    >
      {children}
    </span>
  );
}
