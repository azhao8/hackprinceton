// Seeded demo day: Saturday afternoon at Margaret's home, where she lives on her own and
// her family checks in through Miguel (decision 0052). Everything here is sample data for
// the demo; it reads like a real day on purpose.

import type { FamilyState, Member, Routine, TimelineEvent } from "./types";

export const AFTERNOON = 16 * 60 + 12; // 4:12 pm
export const NIGHT = 2 * 60 + 3; // 2:03 am
export const ALERT_AT = 16 * 60 + 21; // 4:21 pm

export const seedEvents: TimelineEvent[] = [
  {
    id: "e1",
    at: 7 * 60 + 40,
    kind: "wake",
    title: "Up for the day",
    note: "Miguel turned off the night-light and said good morning.",
  },
  { id: "e2", at: 8 * 60 + 15, kind: "walk", title: "Walked to the kitchen", note: "Breakfast. 15 m together, at her usual pace." },
  {
    id: "e3",
    at: 9 * 60,
    kind: "medication",
    title: "Morning pills",
    note: "Miguel asked; she took them with breakfast.",
  },
  {
    id: "e4",
    at: 10 * 60 + 30,
    kind: "water",
    title: "Water, from you",
    quote: "Morning, Mom! Drink up.",
    quoteBy: "Sarah",
  },
  { id: "e5", at: 11 * 60 + 5, kind: "checkIn", title: "You checked in", note: "6 minutes. She showed you the tulips." },
  { id: "e6", at: 12 * 60 + 30, kind: "meal", title: "Lunch at the kitchen table" },
  { id: "e7", at: 13 * 60 + 15, kind: "rest", title: "Afternoon rest", note: "52 minutes. Miguel charged nearby." },
  { id: "e8", at: 14 * 60 + 10, kind: "walk", title: "Garden walk", note: "220 m, her longest this week." },
  {
    id: "e9",
    at: 15 * 60 + 40,
    kind: "message",
    title: "Voice note played",
    quote: "Hi Mom, see you Sunday!",
    quoteBy: "David",
  },
  { id: "e10", at: 16 * 60 + 2, kind: "company", title: "Tea with Ruth", note: "Her neighbor came over. Miguel is keeping them company." },
];

export const seedRoutines: Routine[] = [
  {
    id: "r1",
    kind: "water",
    title: "Water",
    schedule: "Every 2 hours, 9 am – 7 pm",
    detail: "Miguel offers a glass and lets you know she drank.",
    on: true,
  },
  {
    id: "r2",
    kind: "medication",
    title: "Medication",
    schedule: "9 am and 8 pm",
    detail: "Miguel reminds her, asks, and tells you what she said.",
    on: true,
  },
  {
    id: "r3",
    kind: "checkIn",
    title: "Evening check-in",
    schedule: "7:30 pm",
    detail: "Miguel asks if she'd like to call you.",
    on: true,
  },
  {
    id: "r4",
    kind: "nightWalk",
    title: "Night walks",
    schedule: "10 pm – 7 am",
    detail: "A night-light and company on the way to the bathroom.",
    on: true,
  },
  {
    id: "r5",
    kind: "walk",
    title: "Afternoon stroll",
    schedule: "3 pm, if she's been sitting a while",
    detail: "Miguel suggests a short walk together.",
    on: false,
  },
];

export const seedMembers: Member[] = [
  { id: "m1", name: "Sarah", initials: "S", relation: "Daughter", access: "Everything", tone: "sun", you: true },
  { id: "m2", name: "David", initials: "D", relation: "Son", access: "Alerts, messages, sending things", tone: "sky" },
  { id: "m3", name: "Ruth", initials: "R", relation: "Neighbor, has a key", access: "Alerts, loading Miguel's tray", tone: "ember" },
  { id: "m4", name: "Dr. Patel", initials: "P", relation: "Her doctor", access: "Weekly walking summary", tone: "sand", invited: true },
];

export function seedState(now: number): FamilyState {
  return {
    resident: { name: "Margaret", short: "Mom", home: "Margaret's home" },
    viewer: { id: "m1", name: "Sarah" },
    mode: "withMom",
    modeNote: "In the living room with Ruth",
    clock: AFTERNOON,
    clockSetAt: now,
    dayLabel: "Saturday, 14 November",
    events: seedEvents,
    delivery: null,
    checkIn: { phase: "idle" },
    checkInAnswer: "yes",
    alert: null,
    routines: seedRoutines,
    members: seedMembers,
    pace: [0.71, 0.74, 0.69, 0.73, 0.72, 0.75, 0.74],
    requests: {},
  };
}
