import { create } from 'zustand'
import { connectorsApi, type Connector } from '@/lib/api/connectors'

export interface ConnectorsState {
  connectors: Connector[]
  categories: string[]
  isLoading: boolean
  error: string | null

  // Cache de connectors por ID
  connectorCache: Record<string, Connector>

  // Actions
  fetchConnectors: () => Promise<void>
  fetchConnector: (connectorId: string) => Promise<Connector>
  fetchCategories: () => Promise<void>
  getConnectorById: (connectorId: string) => Connector | undefined
  getConnectorsByCategory: (category: string) => Connector[]
  clearError: () => void
}

export const useConnectorsStore = create<ConnectorsState>()((set, get) => ({
  connectors: [],
  categories: [],
  isLoading: false,
  error: null,
  connectorCache: {},

  fetchConnectors: async () => {
    set({ isLoading: true, error: null })
    try {
      const connectors = await connectorsApi.listConnectors()
      const cache: Record<string, Connector> = {}
      connectors.forEach((connector) => {
        cache[connector.id] = connector
      })
      set({
        connectors,
        connectorCache: cache,
        isLoading: false,
      })
    } catch (error) {
      console.error('Error fetching connectors:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch connectors',
        isLoading: false,
      })
    }
  },

  fetchConnector: async (connectorId) => {
    // Check cache first
    const cached = get().connectorCache[connectorId]
    if (cached) {
      return cached
    }

    set({ isLoading: true, error: null })
    try {
      const connector = await connectorsApi.getConnector(connectorId)
      set((state) => ({
        connectors: state.connectors.some((c) => c.id === connectorId)
          ? state.connectors.map((c) => (c.id === connectorId ? connector : c))
          : [...state.connectors, connector],
        connectorCache: {
          ...state.connectorCache,
          [connectorId]: connector,
        },
        isLoading: false,
      }))
      return connector
    } catch (error) {
      console.error('Error fetching connector:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch connector',
        isLoading: false,
      })
      throw error
    }
  },

  fetchCategories: async () => {
    set({ isLoading: true, error: null })
    try {
      const categories = await connectorsApi.getCategories()
      set({ categories, isLoading: false })
    } catch (error) {
      console.error('Error fetching categories:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch categories',
        isLoading: false,
      })
    }
  },

  getConnectorById: (connectorId) => {
    return get().connectorCache[connectorId] || get().connectors.find((c) => c.id === connectorId)
  },

  getConnectorsByCategory: (category) => {
    return get().connectors.filter((c) => c.category === category)
  },

  clearError: () => {
    set({ error: null })
  },
}))

