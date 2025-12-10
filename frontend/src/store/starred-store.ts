import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type StarredType = 'planet' | 'space' | 'crew'

export interface StarredItem {
  id: string
  type: StarredType
  name: string
  description?: string
  icon?: string
  color?: string
  starredAt: Date
}

interface StarredState {
  items: StarredItem[]
  
  // Actions
  toggleStar: (item: Omit<StarredItem, 'starredAt'>) => void
  isStarred: (id: string, type: StarredType) => boolean
  getStarredPlanets: () => StarredItem[]
  getStarredSpaces: () => StarredItem[]
  removeStar: (id: string, type: StarredType) => void
}

export const useStarredStore = create<StarredState>()(
  persist(
    (set, get) => ({
      items: [],
      
      toggleStar: (item) => {
        set((state) => {
          const isAlreadyStarred = state.items.some(
            (i) => i.id === item.id && i.type === item.type
          )
          
          if (isAlreadyStarred) {
            return {
              items: state.items.filter(
                (i) => !(i.id === item.id && i.type === item.type)
              ),
            }
          } else {
            const newItem: StarredItem = {
              ...item,
              starredAt: new Date(),
            }
            return {
              items: [...state.items, newItem],
            }
          }
        })
      },
      
      isStarred: (id, type) => {
        return get().items.some(
          (item) => item.id === id && item.type === type
        )
      },
      
      getStarredPlanets: () => {
        return get().items
          .filter((item) => item.type === 'planet')
          .map((item) => ({
            ...item,
            starredAt: item.starredAt instanceof Date ? item.starredAt : new Date(item.starredAt || Date.now()),
          }))
          .sort((a, b) => {
            const timeA = a.starredAt instanceof Date ? a.starredAt.getTime() : new Date(a.starredAt).getTime()
            const timeB = b.starredAt instanceof Date ? b.starredAt.getTime() : new Date(b.starredAt).getTime()
            return timeB - timeA
          })
      },
      
      getStarredSpaces: () => {
        return get().items
          .filter((item) => item.type === 'space')
          .map((item) => ({
            ...item,
            starredAt: item.starredAt instanceof Date ? item.starredAt : new Date(item.starredAt || Date.now()),
          }))
          .sort((a, b) => {
            const timeA = a.starredAt instanceof Date ? a.starredAt.getTime() : new Date(a.starredAt).getTime()
            const timeB = b.starredAt instanceof Date ? b.starredAt.getTime() : new Date(b.starredAt).getTime()
            return timeB - timeA
          })
      },
      
      removeStar: (id, type) => {
        set((state) => ({
          items: state.items.filter(
            (item) => !(item.id === id && item.type === type)
          ),
        }))
      },
    }),
    {
      name: 'starred-storage',
      partialize: (state) => ({
        items: state.items.map((item) => ({
          ...item,
          starredAt: item.starredAt.toISOString(),
        })),
      }),
      merge: (persistedState: any, currentState) => {
        if (!persistedState) return currentState
        
        const items = (persistedState.items || []).map((item: any) => {
          try {
            return {
              ...item,
              starredAt: item.starredAt ? new Date(item.starredAt) : new Date(),
            }
          } catch (error) {
            // If date parsing fails, use current date
            return {
              ...item,
              starredAt: new Date(),
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

