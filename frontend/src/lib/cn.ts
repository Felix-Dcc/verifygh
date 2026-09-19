import clsx, { type ClassValue } from "clsx";

/**
 * Class-name joiner.
 *
 * Deliberately in its own module with no "use client" directive: server
 * components need it too, and a plain function exported from a client module
 * becomes an unusable client reference when a server component imports it.
 */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}
