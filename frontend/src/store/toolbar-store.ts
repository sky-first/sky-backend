import { create } from 'zustand'

interface ToolbarState {
    activeTool: string | null
    setActiveTool: (tool: string | null) => void
}

export const useToolbarStore = create<ToolbarState>((set) => ({
    activeTool: null,
    setActiveTool: (tool) => set({ activeTool: tool }),
}))

