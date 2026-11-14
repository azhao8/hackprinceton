import type { EventKind, MiguelMode } from "@/lib/family/types";
import type { GlyphName } from "./Glyph";

export const MODE_META: Record<MiguelMode, { label: string; color: string; hollow?: boolean }> = {
  withMom: { label: "With Mom", color: "#e3a21c" },
  delivering: { label: "Delivering", color: "#e07a47" },
  charging: { label: "Charging", color: "#6f95cc" },
  listening: { label: "Listening", color: "#6f95cc" },
  nightLight: { label: "Night-light", color: "#e9a33a" },
  idle: { label: "Idle", color: "#a1988a" },
  offline: { label: "Offline", color: "#a1988a", hollow: true },
};

export const EVENT_GLYPH: Record<EventKind, GlyphName> = {
  wake: "wake",
  walk: "walk",
  water: "water",
  medication: "medication",
  meal: "meal",
  rest: "rest",
  message: "message",
  checkIn: "checkIn",
  company: "company",
  nightLight: "night",
  delivery: "parcel",
  alert: "alert",
};
