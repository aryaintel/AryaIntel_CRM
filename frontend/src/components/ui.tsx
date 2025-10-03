// src/components/ui.tsx
import React from "react";

export function SectionHeader({
  title,
  right,
}: {
  title: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between mt-4 mb-2">
      <h3 className="font-medium">{title}</h3>
      {right}
    </div>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      {children}
    </label>
  );
}

export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="relative bg-white w-[820px] max-w-[95vw] rounded-xl shadow p-5">
        <div className="text-lg font-semibold mb-4">{title}</div>
        {children}
        <button
          onClick={onClose}
          className="absolute top-2 right-2 rounded-md px-2 py-1 text-sm text-gray-500 hover:bg-gray-100"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`bg-white rounded-xl shadow p-4 ${className}`}>
      {children}
    </div>
  );
}

export function KV({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex justify-between items-center text-sm py-0.5 border-b last:border-0">
      <div className="text-gray-500">{label}</div>
      <div className="font-medium tabular-nums">{value}</div>
    </div>
  );
}
