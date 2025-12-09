import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface CanvasLockState {
    isLocked: boolean
    toggleLock: () => void
    setLocked: (locked: boolean) => void
}

export const useCanvasLockStore = create<CanvasLockState>()(
    persist(
        (set) => ({
            isLocked: false,
            toggleLock: () => set((state) => ({ isLocked: !state.isLocked })),
            setLocked: (locked: boolean) => set({ isLocked: locked }),
        }),
        {
            name: 'canvas-lock-storage',
        }
    )
)

