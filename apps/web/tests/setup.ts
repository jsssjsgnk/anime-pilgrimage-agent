import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

Object.defineProperty(window.URL, "createObjectURL", {
  configurable: true,
  value: () => "blob:maplibre-worker",
});

afterEach(() => {
  cleanup();
});
