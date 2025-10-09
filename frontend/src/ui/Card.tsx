import React from "react";
import { card, cardHeader, cardBody, cardFooter } from "./theme";
import { cn } from "./cn";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={cn(card, className)} />;
}

Card.Header = function Header({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={cn(cardHeader, className)} />;
};

Card.Body = function Body({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={cn(cardBody, className)} />;
};

Card.Footer = function Footer({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={cn(cardFooter, "flex items-center justify-end gap-2", className)} />;
};
