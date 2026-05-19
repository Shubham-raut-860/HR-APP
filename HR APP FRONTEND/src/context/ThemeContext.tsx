import * as React from "react"
import { createContext, useContext, useLayoutEffect, useMemo, useState } from "react"

type Theme = "dark" | "light" | "system"
type ResolvedTheme = "dark" | "light"

type ThemeProviderProps = {
  children: React.ReactNode
  defaultTheme?: Theme
  storageKey?: string
}

type ThemeProviderState = {
  theme: Theme
  resolvedTheme: ResolvedTheme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

const initialState: ThemeProviderState = {
  theme: "system",
  resolvedTheme: "light",
  setTheme: () => null,
  toggleTheme: () => null,
}

const ThemeProviderContext = createContext<ThemeProviderState>(initialState)

function getSystemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

function disableTransitionsTemporarily() {
  const css = document.createElement("style")
  css.appendChild(
    document.createTextNode(
      `*,*::before,*::after{-webkit-transition:none!important;transition:none!important}`
    )
  )
  document.head.appendChild(css)

  return () => {
    void window.getComputedStyle(document.body)
    requestAnimationFrame(() => {
      document.head.removeChild(css)
    })
  }
}

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = "vite-ui-theme",
  ...props
}: ThemeProviderProps) {
  const readStoredTheme = (): Theme => {
    const stored = localStorage.getItem(storageKey)
    if (stored === "light" || stored === "dark" || stored === "system") return stored
    return defaultTheme
  }

  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme())
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() => {
    const initialTheme = readStoredTheme()
    return initialTheme === "system" ? getSystemTheme() : initialTheme
  })

  useLayoutEffect(() => {
    const root = window.document.documentElement
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")
    const restoreTransitions = disableTransitionsTemporarily()

    const applyTheme = () => {
      const nextResolvedTheme: ResolvedTheme = theme === "system"
        ? (mediaQuery.matches ? "dark" : "light")
        : theme

      root.classList.remove("light", "dark")
      root.classList.add(nextResolvedTheme)
      root.style.colorScheme = nextResolvedTheme
      setResolvedTheme(nextResolvedTheme)
    }

    applyTheme()
    restoreTransitions()

    if (theme !== "system") return

    const handleSystemThemeChange = () => applyTheme()

    mediaQuery.addEventListener("change", handleSystemThemeChange)
    return () => mediaQuery.removeEventListener("change", handleSystemThemeChange)
  }, [theme])

  const value = useMemo(() => ({
    theme,
    resolvedTheme,
    setTheme: (nextTheme: Theme) => {
      localStorage.setItem(storageKey, nextTheme)
      setThemeState(nextTheme)
    },
    toggleTheme: () => {
      const nextTheme: Theme = resolvedTheme === "dark" ? "light" : "dark"
      localStorage.setItem(storageKey, nextTheme)
      setThemeState(nextTheme)
    },
  }), [theme, resolvedTheme, storageKey])

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  )
}

export const useTheme = () => {
  const context = useContext(ThemeProviderContext)

  if (context === undefined)
    throw new Error("useTheme must be used within a ThemeProvider")

  return context
}
