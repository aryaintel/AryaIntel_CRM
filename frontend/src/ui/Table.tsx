import React from "react";
import { tableHeadRow, cell } from "./theme";
import { cn } from "./cn";

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return <table {...props} className={cn("min-w-full", className)} />;
}

Table.Head = function Head({ children }: { children: React.ReactNode }) {
  return (
    <thead>
      <tr className={tableHeadRow}>{children}</tr>
    </thead>
  );
};

export function Th({ children, className }: React.HTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("font-medium", cell, className)}>{children}</th>;
}
export function Td({ children, className }: React.HTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn(cell, className)}>{children}</td>;
}
