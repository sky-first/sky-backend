import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { spacesApi, type Space, type SpaceCreate, type SpaceUpdate, type SpaceMember, type SpaceMemberCreate, type Crew, type SpaceConnection } from '@/lib/api/spaces'

// Re-export Space type for convenience
export type { Space, SpaceCreate, SpaceUpdate, SpaceMember, SpaceMemberCreate, Crew, SpaceConnection }

export interface SpaceState {
    spaces: Space[]
    currentSpace: Space | null
    isLoading: boolean
    error: string | null
    
    // Space members (per space)
    spaceMembers: Record<string, SpaceMember[]>
    
    // Space crews (per space)
    spaceCrews: Record<string, Crew[]>
    
    // Space connections (per space)
    spaceConnections: Record<string, SpaceConnection[]>
    
    // Actions
    fetchSpaces: (params?: { skip?: number; limit?: number }) => Promise<void>
    fetchSpace: (spaceId: string) => Promise<Space>
    createSpace: (data: SpaceCreate) => Promise<Space>
    updateSpace: (spaceId: string, updates: SpaceUpdate) => Promise<Space>
    deleteSpace: (spaceId: string) => Promise<void>
    setCurrentSpace: (space: Space | null) => void
    
    // Members
    fetchSpaceMembers: (spaceId: string) => Promise<void>
    addSpaceMember: (spaceId: string, data: SpaceMemberCreate) => Promise<SpaceMember>
    removeSpaceMember: (spaceId: string, userId: string) => Promise<void>
    
    // Crews
    fetchSpaceCrews: (spaceId: string) => Promise<void>
    
    // Connections
    fetchSpaceConnections: (spaceId: string) => Promise<void>
}

export const useSpaceStore = create<SpaceState>()(
    persist(
        (set, get) => ({
            spaces: [],
            currentSpace: null,
            isLoading: false,
            error: null,
            spaceMembers: {},
            spaceCrews: {},
            spaceConnections: {},

            fetchSpaces: async (params) => {
                set({ isLoading: true, error: null })
                try {
                    const spaces = await spacesApi.listSpaces(params)
                    const currentSpace = get().currentSpace
                    const resolvedCurrentSpace =
                        currentSpace && spaces.some(s => s.id === currentSpace.id)
                            ? currentSpace
                            : (spaces[0] || null)

                    set({
                        spaces,
                        currentSpace: resolvedCurrentSpace,
                        isLoading: false,
                    })
                } catch (error) {
                    console.error('Error fetching spaces:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch spaces',
                        isLoading: false 
                    })
                }
            },

            fetchSpace: async (spaceId) => {
                set({ isLoading: true, error: null })
                try {
                    const space = await spacesApi.getSpace(spaceId)
                    set((state) => ({
                        spaces: state.spaces.some(s => s.id === spaceId)
                            ? state.spaces.map(s => s.id === spaceId ? space : s)
                            : [...state.spaces, space],
                        currentSpace: space,
                        isLoading: false,
                    }))
                    
                    // Add to recents (lazy import to avoid circular dependency)
                    import('./recents-store').then(({ useRecentsStore }) => {
                        useRecentsStore.getState().addRecent({
                            id: space.id,
                            type: 'space',
                            name: space.name,
                            description: space.description,
                        })
                    }).catch(() => {
                        // Silently fail if recents store is not available
                    })
                    
                    return space
                } catch (error) {
                    console.error('Error fetching space:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch space',
                        isLoading: false 
                    })
                    throw error
                }
            },

            createSpace: async (data) => {
                set({ isLoading: true, error: null })
                try {
                    const space = await spacesApi.createSpace(data)
                    set((state) => ({
                        spaces: [...state.spaces, space],
                        currentSpace: space, // Set as current
                        isLoading: false,
                    }))
                    return space
                } catch (error) {
                    console.error('Error creating space:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to create space',
                        isLoading: false 
                    })
                    throw error
                }
            },

            updateSpace: async (spaceId, updates) => {
                set({ isLoading: true, error: null })
                try {
                    const space = await spacesApi.updateSpace(spaceId, updates)
                    set((state) => ({
                        spaces: state.spaces.map((s) =>
                            s.id === spaceId ? space : s
                        ),
                        currentSpace: state.currentSpace?.id === spaceId
                            ? space
                            : state.currentSpace,
                        isLoading: false,
                    }))
                    return space
                } catch (error) {
                    console.error('Error updating space:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to update space',
                        isLoading: false 
                    })
                    throw error
                }
            },

            deleteSpace: async (spaceId) => {
                set({ isLoading: true, error: null })
                try {
                    await spacesApi.deleteSpace(spaceId)
                    set((state) => ({
                        spaces: state.spaces.filter((s) => s.id !== spaceId),
                        currentSpace: state.currentSpace?.id === spaceId
                            ? null
                            : state.currentSpace,
                        // Clean up related data
                        spaceMembers: Object.fromEntries(
                            Object.entries(state.spaceMembers).filter(([key]) => key !== spaceId)
                        ),
                        spaceCrews: Object.fromEntries(
                            Object.entries(state.spaceCrews).filter(([key]) => key !== spaceId)
                        ),
                        spaceConnections: Object.fromEntries(
                            Object.entries(state.spaceConnections).filter(([key]) => key !== spaceId)
                        ),
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error deleting space:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to delete space',
                        isLoading: false 
                    })
                    throw error
                }
            },

            setCurrentSpace: (space) => {
                set({ currentSpace: space })
                
                // Add to recents (lazy import to avoid circular dependency)
                if (space) {
                    import('./recents-store').then(({ useRecentsStore }) => {
                        useRecentsStore.getState().addRecent({
                            id: space.id,
                            type: 'space',
                            name: space.name,
                            description: space.description,
                        })
                    }).catch(() => {
                        // Silently fail if recents store is not available
                    })
                }
            },

            fetchSpaceMembers: async (spaceId) => {
                set({ isLoading: true, error: null })
                try {
                    const members = await spacesApi.getSpaceMembers(spaceId)
                    set((state) => ({
                        spaceMembers: {
                            ...state.spaceMembers,
                            [spaceId]: members,
                        },
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error fetching space members:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch space members',
                        isLoading: false 
                    })
                }
            },

            addSpaceMember: async (spaceId, data) => {
                set({ isLoading: true, error: null })
                try {
                    const member = await spacesApi.addSpaceMember(spaceId, data)
                    set((state) => ({
                        spaceMembers: {
                            ...state.spaceMembers,
                            [spaceId]: [...(state.spaceMembers[spaceId] || []), member],
                        },
                        isLoading: false,
                    }))
                    return member
                } catch (error) {
                    console.error('Error adding space member:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to add space member',
                        isLoading: false 
                    })
                    throw error
                }
            },

            removeSpaceMember: async (spaceId, userId) => {
                set({ isLoading: true, error: null })
                try {
                    await spacesApi.removeSpaceMember(spaceId, userId)
                    set((state) => ({
                        spaceMembers: {
                            ...state.spaceMembers,
                            [spaceId]: (state.spaceMembers[spaceId] || []).filter(
                                m => m.user_id !== userId
                            ),
                        },
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error removing space member:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to remove space member',
                        isLoading: false 
                    })
                    throw error
                }
            },

            fetchSpaceCrews: async (spaceId) => {
                set({ isLoading: true, error: null })
                try {
                    console.log(`[SpaceStore] Fetching crews for space ${spaceId}`)
                    const crews = await spacesApi.getSpaceCrews(spaceId)
                    console.log(`[SpaceStore] Received ${crews?.length || 0} crews for space ${spaceId}:`, crews)
                    set((state) => ({
                        spaceCrews: {
                            ...state.spaceCrews,
                            [spaceId]: crews,
                        },
                        isLoading: false,
                    }))
                    console.log(`[SpaceStore] Updated spaceCrews for ${spaceId}`)
                } catch (error) {
                    console.error(`[SpaceStore] Error fetching space crews for ${spaceId}:`, error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch space crews',
                        isLoading: false 
                    })
                }
            },

            fetchSpaceConnections: async (spaceId) => {
                set({ isLoading: true, error: null })
                try {
                    const connections = await spacesApi.getSpaceConnections(spaceId)
                    set((state) => ({
                        spaceConnections: {
                            ...state.spaceConnections,
                            [spaceId]: connections,
                        },
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error fetching space connections:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch space connections',
                        isLoading: false 
                    })
                }
            },
        }),
        {
            name: 'space-storage',
            partialize: (state) => ({
                currentSpace: state.currentSpace,
            }),
        }
    )
)

