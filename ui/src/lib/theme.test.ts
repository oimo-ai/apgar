import { act, renderHook } from "@testing-library/react";

import { useTheme } from "@/lib/theme";

function installMedia(matches: boolean) {
  const listeners = new Set<(event: { matches: boolean }) => void>();
  const media = {
    matches,
    media: "(prefers-color-scheme: dark)",
    addEventListener: (_name: string, listener: (event: { matches: boolean }) => void) => {
      listeners.add(listener);
    },
    removeEventListener: (_name: string, listener: (event: { matches: boolean }) => void) => {
      listeners.delete(listener);
    },
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
    onchange: null,
  };
  window.matchMedia = (() => media) as unknown as typeof window.matchMedia;
  return {
    setMatches(next: boolean) {
      media.matches = next;
      for (const listener of listeners) {
        listener({ matches: next });
      }
    },
  };
}

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.dataset.theme = "";
  });

  it("resolves system from matchMedia by default", () => {
    installMedia(true);
    const { result } = renderHook(() => useTheme());
    expect(result.current.choice).toBe("system");
    expect(result.current.resolved).toBe("dark");
  });

  it("writes localStorage and data-theme for an explicit choice", () => {
    installMedia(false);
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setChoice("dark"));
    expect(localStorage.getItem("apgar-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("follows a media change while the choice is system", () => {
    const media = installMedia(false);
    const { result } = renderHook(() => useTheme());
    expect(result.current.resolved).toBe("light");
    act(() => media.setMatches(true));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(result.current.resolved).toBe("dark");
  });
});
