import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { planetsApi, type Planet as ApiPlanet, type PlanetCreate } from '@/lib/api/planets'
import { hexToColorName, colorNameToHex } from '@/lib/utils/planet-colors'
import { SessionExpiredError } from '@/lib/api/client'

export interface Planet {
    id: string
    name: string
    description?: string
    type: 'personal' | 'team'
    color: string
    icon?: string
    memberCount?: number
    lastAccessed?: Date
    isActive?: boolean
    owner_id?: string
    created_at?: string
    updated_at?: string
}

interface PlanetState {
    planets: Planet[]
    currentPlanet: Planet | null
    isLoading: boolean
    error: string | null
    // Actions
    setCurrentPlanet: (planet: Planet | null) => void
    fetchPlanets: (params?: { type?: 'personal' | 'team'; search?: string }) => Promise<void>
    createPlanet: (data: PlanetCreate) => Promise<Planet>
    updatePlanet: (id: string, updates: Partial<Planet>) => Promise<void>
    deletePlanet: (id: string) => Promise<void>
    switchPlanet: (planetId: string) => Promise<void>
    getPersonalPlanets: () => Planet[]
    getTeamPlanets: () => Planet[]
    // Legacy methods for backward compatibility
    addPlanet: (planet: Omit<Planet, 'id' | 'lastAccessed'>) => void
}

// Helper function to convert API planet to store planet
const apiToStorePlanet = (api: ApiPlanet): Planet => ({
    id: api.id,
    name: api.name,
    description: api.description,
    type: api.type,
    color: hexToColorName(api.color), // Convert hex to color name for frontend
    icon: api.icon,
    owner_id: api.owner_id,
    isActive: api.is_active,
    lastAccessed: api.last_accessed ? new Date(api.last_accessed) : undefined,
    created_at: api.created_at,
    updated_at: api.updated_at,
})

// Helper function to convert store planet to API format
const storeToApiPlanet = (store: Partial<Planet>): Partial<ApiPlanet> => {
    const api: any = {}
    if (store.name !== undefined) api.name = store.name
    if (store.description !== undefined) api.description = store.description
    if (store.type !== undefined) api.type = store.type
    if (store.color !== undefined) api.color = colorNameToHex(store.color) // Convert color name to hex
    if (store.icon !== undefined) api.icon = store.icon
    return api
}

export const usePlanetStore = create<PlanetState>()(
    persist(
        (set, get) => ({
            planets: [],
            currentPlanet: null,
            isLoading: false,
            error: null,
            
            setCurrentPlanet: (planet) => {
                set((state) => ({
                    currentPlanet: planet,
                    planets: state.planets.map((w) => ({
                        ...w,
                        isActive: w.id === planet?.id,
                        lastAccessed: w.id === planet?.id ? new Date() : w.lastAccessed,
                    })),
                }))
                
                // Add to recents (lazy import to avoid circular dependency)
                if (planet) {
                    import('./recents-store').then(({ useRecentsStore }) => {
                        useRecentsStore.getState().addRecent({
                            id: planet.id,
                            type: 'planet',
                            name: planet.name,
                            description: planet.description,
                            icon: planet.icon,
                            color: planet.color,
                        })
                    }).catch(() => {
                        // Silently fail if recents store is not available
                    })
                }
            },
            
            fetchPlanets: async (params) => {
                set({ isLoading: true, error: null })
                try {
                    const apiPlanets = await planetsApi.listPlanets(params)
                    const planets = apiPlanets.map(apiToStorePlanet)
                    
                    // Set active planet if not set
                    const activePlanet = planets.find(w => w.isActive) || planets[0] || null
                    
                    set({ 
                        planets,
                        currentPlanet: get().currentPlanet || activePlanet,
                        isLoading: false 
                    })
                } catch (error) {
                    // Don't log session expired errors - they're expected and handled by user-store
                    if (error instanceof SessionExpiredError) {
                        // Session expired - clear planets silently (user will be redirected to login)
                        set({ 
                            planets: [],
                            currentPlanet: null,
                            isLoading: false 
                        })
                        return
                    }
                    
                    // Log other errors
                    if (process.env.NODE_ENV === 'development') {
                        console.error('Error fetching planets:', error)
                    }
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch planets',
                        isLoading: false 
                    })
                }
            },
            
            createPlanet: async (data) => {
                set({ isLoading: true, error: null })
                try {
                    // Convert color name to hex for API
                    const apiData: PlanetCreate = {
                        ...data,
                        color: colorNameToHex(data.color),
                    }
                    const apiPlanet = await planetsApi.createPlanet(apiData)
                    const planet = apiToStorePlanet(apiPlanet)
                    
                    set((state) => ({
                        planets: [...state.planets, planet],
                        currentPlanet: planet, // Set as active
                        isLoading: false,
                    }))
                    
                    return planet
                } catch (error) {
                    console.error('Error creating planet:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to create planet',
                        isLoading: false 
                    })
                    throw error
                }
            },
            
            updatePlanet: async (id, updates) => {
                set({ isLoading: true, error: null })
                try {
                    // Convert store updates to API format
                    const apiUpdates: any = {}
                    if (updates.name !== undefined) apiUpdates.name = updates.name
                    if (updates.description !== undefined) apiUpdates.description = updates.description
                    if (updates.color !== undefined) apiUpdates.color = colorNameToHex(updates.color) // Convert color name to hex
                    if (updates.icon !== undefined) apiUpdates.icon = updates.icon
                    
                    const apiPlanet = await planetsApi.updatePlanet(id, apiUpdates)
                    const updatedPlanet = apiToStorePlanet(apiPlanet)
                    
                    set((state) => ({
                        planets: state.planets.map((w) =>
                            w.id === id ? updatedPlanet : w
                        ),
                        currentPlanet: state.currentPlanet?.id === id 
                            ? updatedPlanet 
                            : state.currentPlanet,
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error updating planet:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to update planet',
                        isLoading: false 
                    })
                    throw error
                }
            },
            
            deletePlanet: async (id) => {
                set({ isLoading: true, error: null })
                try {
                    await planetsApi.deletePlanet(id)
                    set((state) => ({
                        planets: state.planets.filter((w) => w.id !== id),
                        currentPlanet: state.currentPlanet?.id === id 
                            ? null 
                            : state.currentPlanet,
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error deleting planet:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to delete planet',
                        isLoading: false 
                    })
                    throw error
                }
            },
            
            switchPlanet: async (planetId) => {
                set({ isLoading: true, error: null })
                try {
                    const apiPlanet = await planetsApi.switchPlanet(planetId)
                    const planet = apiToStorePlanet(apiPlanet)
                    
                    set((state) => ({
                        currentPlanet: planet,
                        planets: state.planets.map((w) => ({
                            ...w,
                            isActive: w.id === planetId,
                            lastAccessed: w.id === planetId ? new Date() : w.lastAccessed,
                        })),
                        isLoading: false,
                    }))
                    
                    // Add to recents (lazy import to avoid circular dependency)
                    import('./recents-store').then(({ useRecentsStore }) => {
                        useRecentsStore.getState().addRecent({
                            id: planet.id,
                            type: 'planet',
                            name: planet.name,
                            description: planet.description,
                            icon: planet.icon,
                            color: planet.color,
                        })
                    }).catch(() => {
                        // Silently fail if recents store is not available
                    })
                } catch (error) {
                    console.error('Error switching planet:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to switch planet',
                        isLoading: false 
                    })
                    throw error
                }
            },
            
            getPersonalPlanets: () => {
                return get().planets.filter((w) => w.type === 'personal')
            },
            
            getTeamPlanets: () => {
                return get().planets.filter((w) => w.type === 'team')
            },
            
            // Legacy method for backward compatibility
            addPlanet: (planet) => {
                const newPlanet: Planet = {
                    ...planet,
                    id: Date.now().toString(),
                    lastAccessed: new Date(),
                }
                set((state) => ({
                    planets: [...state.planets, newPlanet],
                }))
            },
        }),
        {
            name: 'planet-storage',
            partialize: (state) => ({
                planets: state.planets.map(w => ({
                    ...w,
                    lastAccessed: w.lastAccessed?.toISOString(),
                })),
                currentPlanet: state.currentPlanet ? {
                    ...state.currentPlanet,
                    lastAccessed: state.currentPlanet.lastAccessed?.toISOString(),
                } : null,
            }),
            merge: (persistedState: any, currentState) => {
                if (!persistedState) return currentState
                
                const planets = (persistedState.planets || []).map((w: any) => ({
                    ...w,
                    lastAccessed: w.lastAccessed ? new Date(w.lastAccessed) : undefined,
                }))
                
                let currentPlanet = null
                if (persistedState.currentPlanet) {
                    currentPlanet = {
                        ...persistedState.currentPlanet,
                        lastAccessed: persistedState.currentPlanet.lastAccessed 
                            ? new Date(persistedState.currentPlanet.lastAccessed) 
                            : undefined,
                    }
                } else {
                    currentPlanet = planets.find((w: Planet) => w.isActive) || planets[0] || null
                }
                
                return {
                    ...currentState,
                    planets,
                    currentPlanet,
                }
            },
        }
    )
)

