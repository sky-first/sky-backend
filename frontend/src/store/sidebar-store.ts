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
            isOpen: false, // Closed by default - opens on hover/click
            setIsOpen: (isOpen) => set({ isOpen }),
            toggle: () => set((state) => ({ isOpen: !state.isOpen })),
        }),
        {
            name: 'sidebar-storage',
        }
    )
)

