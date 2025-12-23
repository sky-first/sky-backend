import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { crewsApi, type Crew, type CrewCreate, type CrewUpdate, type CrewMember, type CrewMemberCreate, type CrewMemberUpdate } from '@/lib/api/crews'

export interface CrewState {
    crews: Crew[]
    currentCrew: Crew | null
    isLoading: boolean
    error: string | null
    
    // Crew members (per crew)
    crewMembers: Record<string, CrewMember[]>
    
    // Actions
    fetchCrews: (params?: { space_id?: string; skip?: number; limit?: number }) => Promise<void>
    fetchCrew: (crewId: string) => Promise<Crew>
    createCrew: (data: CrewCreate) => Promise<Crew>
    updateCrew: (crewId: string, updates: CrewUpdate) => Promise<Crew>
    deleteCrew: (crewId: string) => Promise<void>
    setCurrentCrew: (crew: Crew | null) => void
    
    // Members
    fetchCrewMembers: (crewId: string) => Promise<void>
    addCrewMember: (crewId: string, data: CrewMemberCreate) => Promise<CrewMember>
    removeCrewMember: (crewId: string, userId: string) => Promise<void>
    updateCrewMemberRole: (crewId: string, userId: string, role: string) => Promise<CrewMember>
}

export const useCrewStore = create<CrewState>()(
    persist(
        (set, get) => ({
            crews: [],
            currentCrew: null,
            isLoading: false,
            error: null,
            crewMembers: {},

            fetchCrews: async (params) => {
                set({ isLoading: true, error: null })
                try {
                    const crews = await crewsApi.listCrews(params)
                    set({ 
                        crews,
                        isLoading: false 
                    })
                } catch (error) {
                    console.error('Error fetching crews:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch crews',
                        isLoading: false 
                    })
                }
            },

            fetchCrew: async (crewId) => {
                set({ isLoading: true, error: null })
                try {
                    const crew = await crewsApi.getCrew(crewId)
                    set((state) => ({
                        crews: state.crews.some(c => c.id === crewId)
                            ? state.crews.map(c => c.id === crewId ? crew : c)
                            : [...state.crews, crew],
                        currentCrew: crew,
                        isLoading: false,
                    }))
                    return crew
                } catch (error) {
                    console.error('Error fetching crew:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch crew',
                        isLoading: false 
                    })
                    throw error
                }
            },

            createCrew: async (data) => {
                set({ isLoading: true, error: null })
                try {
                    const crew = await crewsApi.createCrew(data)
                    set((state) => ({
                        crews: [...state.crews, crew],
                        currentCrew: crew, // Set as current
                        isLoading: false,
                    }))
                    return crew
                } catch (error) {
                    console.error('Error creating crew:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to create crew',
                        isLoading: false 
                    })
                    throw error
                }
            },

            updateCrew: async (crewId, updates) => {
                set({ isLoading: true, error: null })
                try {
                    const crew = await crewsApi.updateCrew(crewId, updates)
                    set((state) => ({
                        crews: state.crews.map((c) =>
                            c.id === crewId ? crew : c
                        ),
                        currentCrew: state.currentCrew?.id === crewId
                            ? crew
                            : state.currentCrew,
                        isLoading: false,
                    }))
                    return crew
                } catch (error) {
                    console.error('Error updating crew:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to update crew',
                        isLoading: false 
                    })
                    throw error
                }
            },

            deleteCrew: async (crewId) => {
                set({ isLoading: true, error: null })
                try {
                    await crewsApi.deleteCrew(crewId)
                    set((state) => ({
                        crews: state.crews.filter((c) => c.id !== crewId),
                        currentCrew: state.currentCrew?.id === crewId
                            ? null
                            : state.currentCrew,
                        // Clean up related data
                        crewMembers: Object.fromEntries(
                            Object.entries(state.crewMembers).filter(([key]) => key !== crewId)
                        ),
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error deleting crew:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to delete crew',
                        isLoading: false 
                    })
                    throw error
                }
            },

            setCurrentCrew: (crew) => {
                set({ currentCrew: crew })
            },

            fetchCrewMembers: async (crewId) => {
                set({ isLoading: true, error: null })
                try {
                    const members = await crewsApi.getCrewMembers(crewId)
                    set((state) => ({
                        crewMembers: {
                            ...state.crewMembers,
                            [crewId]: members,
                        },
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error fetching crew members:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch crew members',
                        isLoading: false 
                    })
                }
            },

            addCrewMember: async (crewId, data) => {
                set({ isLoading: true, error: null })
                try {
                    const member = await crewsApi.addCrewMember(crewId, data)
                    set((state) => ({
                        crewMembers: {
                            ...state.crewMembers,
                            [crewId]: [...(state.crewMembers[crewId] || []), member],
                        },
                        isLoading: false,
                    }))
                    return member
                } catch (error) {
                    console.error('Error adding crew member:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to add crew member',
                        isLoading: false 
                    })
                    throw error
                }
            },

            removeCrewMember: async (crewId, userId) => {
                set({ isLoading: true, error: null })
                try {
                    await crewsApi.removeCrewMember(crewId, userId)
                    set((state) => ({
                        crewMembers: {
                            ...state.crewMembers,
                            [crewId]: (state.crewMembers[crewId] || []).filter(
                                m => m.user_id !== userId
                            ),
                        },
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error removing crew member:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to remove crew member',
                        isLoading: false 
                    })
                    throw error
                }
            },

            updateCrewMemberRole: async (crewId, userId, role) => {
                set({ isLoading: true, error: null })
                try {
                    const roleString = typeof role === 'string' ? role : (role as any).role || 'explorer'
                    const member = await crewsApi.updateCrewMemberRole(crewId, userId, roleString)
                    set((state) => ({
                        crewMembers: {
                            ...state.crewMembers,
                            [crewId]: (state.crewMembers[crewId] || []).map(m =>
                                m.user_id === userId ? member : m
                            ),
                        },
                        isLoading: false,
                    }))
                    return member
                } catch (error) {
                    console.error('Error updating crew member role:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to update crew member role',
                        isLoading: false 
                    })
                    throw error
                }
            },
        }),
        {
            name: 'crew-storage',
            partialize: (state) => ({
                currentCrew: state.currentCrew,
            }),
        }
    )
)

