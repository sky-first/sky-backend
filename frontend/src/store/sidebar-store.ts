import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SidebarState {
    isOpen: boolean
    setIsOpen: (isOpen: boolean) => void
    toggle: () => void
}

export const useSidebarStore = create<SidebarState>()(
    persist(
        (set) => ({
            isOpen: true, // Open by default on desktop
            setIsOpen: (isOpen) => set({ isOpen }),
            toggle: () => set((state) => ({ isOpen: !state.isOpen })),
        }),
        {
            name: 'sidebar-storage',
        }
    )
)

