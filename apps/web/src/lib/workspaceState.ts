import { useCallback, useState, useSyncExternalStore } from "react";

// Workspace state that outlives the page. It stays in memory while the student browses the
// rest of the site, and in sessionStorage so a reload in the same tab restores it too.
const PREFIX = "vidyapulse-workspace:";

const values = new Map<string, unknown>();
const listeners = new Map<string, Set<() => void>>();

/** Turns a value saved before a reload back into live state, e.g. to end an interrupted request. */
export type Revive<T> = (saved: T) => T;

function load<T>(key: string, initial: T, revive?: Revive<T>): T {
  if (values.has(key)) return values.get(key) as T;
  let value = initial;
  try {
    const raw = window.sessionStorage.getItem(PREFIX + key);
    if (raw !== null) {
      const saved = JSON.parse(raw) as T;
      value = revive ? revive(saved) : saved;
    }
  } catch {
    // Storage blocked or unreadable: start fresh
  }
  values.set(key, value);
  return value;
}

/** Stores a value without re-rendering anyone, for state read only on the next visit. */
export function saveState<T>(key: string, value: T) {
  values.set(key, value);
  try {
    window.sessionStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // Storage full or blocked: still kept in memory for this visit
  }
}

/** The saved value, or `initial` when there is none. */
export function readState<T>(key: string, initial: T): T {
  return load(key, initial);
}

function setState<T>(key: string, next: T | ((prev: T) => T), initial: T) {
  const value =
    typeof next === "function"
      ? (next as (prev: T) => T)(load(key, initial))
      : next;
  saveState(key, value);
  listeners.get(key)?.forEach((listener) => listener());
}

/**
 * useState that survives leaving the workspace and coming back. Updates made after the
 * component has unmounted, such as an answer arriving, are kept and shown on return.
 * Pass key null to use `initial` without saving anything.
 */
export function usePersistentState<T>(
  key: string | null,
  initial: T,
  revive?: Revive<T>,
): [T, (next: T | ((prev: T) => T)) => void] {
  // The first initial value, so the snapshot stays the same object between renders
  const [fallback] = useState(initial);

  const subscribe = useCallback(
    (listener: () => void) => {
      if (!key) return () => {};
      const set = listeners.get(key) ?? new Set();
      set.add(listener);
      listeners.set(key, set);
      return () => set.delete(listener);
    },
    [key],
  );

  const value = useSyncExternalStore(
    subscribe,
    () => (key ? load(key, fallback, revive) : fallback),
    () => fallback,
  );

  const update = useCallback(
    (next: T | ((prev: T) => T)) => {
      if (key) setState(key, next, fallback);
    },
    [key, fallback],
  );

  return [value, update];
}
