"use client"

import { create } from "zustand"
import { persist } from "zustand/middleware"

type AliasState = {
  aliases: Record<string, string>
  setAlias: (key: string, value: string) => void
  clearAlias: (key: string) => void
  getAlias: (key: string) => string | undefined
}

export const useTitleAliasStore = create<AliasState>()(
  persist(
    (set, get) => ({
      aliases: {},
      setAlias: (key, value) =>
        set((state) => ({
          aliases: {
            ...state.aliases,
            [key]: value,
          },
        })),
      clearAlias: (key) =>
        set((state) => {
          const next = { ...state.aliases }
          delete next[key]
          return { aliases: next }
        }),
      getAlias: (key) => get().aliases[key],
    }),
    { name: "title-alias-store" }
  )
)

