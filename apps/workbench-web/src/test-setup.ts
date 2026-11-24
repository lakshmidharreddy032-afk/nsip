import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import "./lib/i18n";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// jsdom lacks these browser APIs used by charts, panels and dialogs.
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
Element.prototype.scrollIntoView = vi.fn();
window.matchMedia = window.matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false }) as unknown as MediaQueryList);
URL.createObjectURL = URL.createObjectURL || (() => "blob:test");
URL.revokeObjectURL = URL.revokeObjectURL || (() => undefined);

afterEach(() => cleanup());
