import React from "react";
import { input, select, textarea } from "./theme";
import { cn } from "./cn";

export function Label({ children, className }: React.HTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("block text-xs text-gray-600 mb-1", className)}>{children}</label>;
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => <input ref={ref} className={cn(input, className)} {...props} />
);
Input.displayName = "Input";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select ref={ref} className={cn(select, className)} {...props}>
      {children}
    </select>
  )
);
Select.displayName = "Select";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => <textarea ref={ref} className={cn(textarea, className)} {...props} />
);
Textarea.displayName = "Textarea";
