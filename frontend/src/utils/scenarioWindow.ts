//src>utils>scenarioWindow.ts

import { ScenarioDetail } from "../types/scenario";

export function getScenarioWindow(data: ScenarioDetail | null) {
  if (!data) return null;
  const start = new Date(data.start_date);
  if (Number.isNaN(start.getTime())) return null;
  const startY = start.getUTCFullYear();
  const startM = start.getUTCMonth() + 1;
  const end = new Date(Date.UTC(startY, startM - 1 + (data.months - 1), 1));
  const endY = end.getUTCFullYear();
  const endM = end.getUTCMonth() + 1;
  return { startY, startM, endY, endM, start, end };
}

export function isInWindow(data: ScenarioDetail, y: number, m: number) {
  const w = getScenarioWindow(data);
  if (!w) return true;
  const a = y * 100 + m;
  const s = w.startY * 100 + w.startM;
  const e = w.endY * 100 + w.endM;
  return a >= s && a <= e;
}

export function monthIndex(data: ScenarioDetail, year: number, month: number) {
  const w = getScenarioWindow(data);
  if (!w) return 0;
  return (year - w.startY) * 12 + (month - w.startM);
}

export function buildMonthsList(data: ScenarioDetail | null) {
  const w = getScenarioWindow(data);
  if (!w || !data) return [];
  const out: { y: number; m: number }[] = [];
  let y = w.startY, m = w.startM;
  for (let i = 0; i < data.months; i++) {
    out.push({ y, m });
    m++; if (m > 12) { m = 1; y++; }
  }
  return out;
}
