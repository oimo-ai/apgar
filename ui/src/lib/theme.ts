import { useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const KEY = "apgar-theme";

export function readChoice(): ThemeChoice {
  const raw = localStorage.getItem(KEY);
  if (raw === "light" || raw === "dark" || raw === "system") {
    return raw;
  }
  return "system";
}

export function resolveTheme(choice: ThemeChoice): "light" | "dark" {
  if (choice === "light" || choice === "dark") {
    return choice;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyChoice(choice: ThemeChoice): "light" | "dark" {
  const resolved = resolveTheme(choice);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themeChoice = choice;
  localStorage.setItem(KEY, choice);
  return resolved;
}

export function useTheme(): {
  choice: ThemeChoice;
  resolved: "light" | "dark";
  setChoice: (choice: ThemeChoice) => void;
} {
  const [choice, setChoiceState] = useState<ThemeChoice>(() => readChoice());
  const [resolved, setResolved] = useState<"light" | "dark">(() => resolveTheme(readChoice()));

  useEffect(() => {
    if (choice !== "system") {
      return;
    }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (): void => {
      const next = media.matches ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      document.documentElement.dataset.themeChoice = "system";
      setResolved(next);
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [choice]);

  const setChoice = (next: ThemeChoice): void => {
    setResolved(applyChoice(next));
    setChoiceState(next);
  };

  return { choice, resolved, setChoice };
}
