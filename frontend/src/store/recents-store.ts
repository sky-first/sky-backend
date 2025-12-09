import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type RecentType = 'planet' | 'space'

export interface RecentItem {
  id: string
  type: RecentType
  name: string
  description?: string
  icon?: string
  color?: string
  accessedAt: Date
}

interface RecentsState {
  items: RecentItem[]
  maxItems: number
  
  // Actions
  addRecent: (item: Omit<RecentItem, 'accessedAt'>) => void
  getRecentPlanets: () => RecentItem[]
  getRecentSpaces: () => RecentItem[]
  clearRecents: () => void
  removeRecent: (id: string, type: RecentType) => void
}

export const useRecentsStore = create<RecentsState>()(
  persist(
    (set, get) => ({
      items: [],
      maxItems: 20,
      
      addRecent: (item) => {
        set((state) => {
          const filtered = state.items.filter(
            (i) => !(i.id === item.id && i.type === item.type)
          )
          
          const newItem: RecentItem = {
            ...item,
            accessedAt: new Date(),
          }
          
          const updated = [newItem, ...filtered].slice(0, state.maxItems)
          
          return { items: updated }
        })
      },
      
      getRecentPlanets: () => {
        return get().items
          .filter((item) => item.type === 'planet')
          .map((item) => ({
            ...item,
            accessedAt: item.accessedAt instanceof Date ? item.accessedAt : new Date(item.accessedAt || Date.now()),
          }))
          .sort((a, b) => {
            const timeA = a.accessedAt instanceof Date ? a.accessedAt.getTime() : new Date(a.accessedAt).getTime()
            const timeB = b.accessedAt instanceof Date ? b.accessedAt.getTime() : new Date(b.accessedAt).getTime()
            return timeB - timeA
          })
      },
      
      getRecentSpaces: () => {
        return get().items
          .filter((item) => item.type === 'space')
          .map((item) => ({
            ...item,
            accessedAt: item.accessedAt instanceof Date ? item.accessedAt : new Date(item.accessedAt || Date.now()),
          }))
          .sort((a, b) => {
            const timeA = a.accessedAt instanceof Date ? a.accessedAt.getTime() : new Date(a.accessedAt).getTime()
            const timeB = b.accessedAt instanceof Date ? b.accessedAt.getTime() : new Date(b.accessedAt).getTime()
            return timeB - timeA
          })
      },
      
      clearRecents: () => {
        set({ items: [] })
      },
      
      removeRecent: (id, type) => {
        set((state) => ({
          items: state.items.filter(
            (item) => !(item.id === id && item.type === type)
          ),
        }))
      },
    }),
    {
      name: 'recents-storage',
      partialize: (state) => ({
        items: state.items.map((item) => ({
          ...item,
          accessedAt: item.accessedAt.toISOString(),
        })),
      }),
      merge: (persistedState: any, currentState) => {
        if (!persistedState) return currentState
        
        const items = (persistedState.items || []).map((item: any) => {
          try {
            return {
              ...item,
              accessedAt: item.accessedAt ? new Date(item.accessedAt) : new Date(),
            }
          } catch (error) {
            // If date parsing fails, use current date
            return {
              ...item,
              accessedAt: new Date(),
            }
          }
        })
        
        return {
          ...currentState,
          items,
        }
      },
    }
  )
)

