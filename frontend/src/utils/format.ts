import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export function formatDate(iso?: string | null, withTime = false) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
}

export const ENTITY_LABELS: Record<string, string> = {
  PERSON: "People",
  LOCATION: "Locations",
  DATE: "Dates",
  TIME: "Times",
  VEHICLE_NUMBER: "Vehicle numbers",
  PHONE: "Phone numbers",
  CASE_ID: "Case IDs",
  FIR_NUMBER: "FIR numbers",
  LEGAL_SECTION: "Legal sections",
  AMOUNT: "Amounts",
  POLICE_STATION: "Police stations",
};
