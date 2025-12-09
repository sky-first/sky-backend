import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { 
  connectionsApi, 
  type Connection, 
  type ConnectionCreate, 
  type ConnectionUpdate,
  type ConnectionTestResponse,
  type ConnectionSyncResponse,
  type ConnectionMetadataResponse,
  type ConnectionStatusResponse,
  type ConnectionValidateResponse,
  type TableMetadata,
} from '@/lib/api/connections'

export interface ConnectionState {
  connections: Connection[]
  currentConnection: Connection | null
  isLoading: boolean
  error: string | null
  
  // Actions
  fetchConnections: (params?: { 
    status?: 'active' | 'inactive' | 'error'
    connector_id?: string
    skip?: number
    limit?: number
  }) => Promise<void>
  fetchConnection: (connectionId: string) => Promise<Connection>
  createConnection: (data: ConnectionCreate) => Promise<Connection>
  updateConnection: (connectionId: string, updates: ConnectionUpdate) => Promise<Connection>
  deleteConnection: (connectionId: string) => Promise<void>
  setCurrentConnection: (connection: Connection | null) => void
  
  // Connection operations
  testConnection: (connectionId: string) => Promise<ConnectionTestResponse>
  syncConnection: (connectionId: string) => Promise<ConnectionSyncResponse>
  getConnectionMetadata: (connectionId: string) => Promise<ConnectionMetadataResponse>
  getConnectionTables: (connectionId: string) => Promise<TableMetadata[]>
  getConnectionSchemas: (connectionId: string) => Promise<string[]>
  getConnectionStatus: (connectionId: string) => Promise<ConnectionStatusResponse>
  validateConnection: (connectionId: string) => Promise<ConnectionValidateResponse>
}

export const useConnectionStore = create<ConnectionState>()(
  persist(
    (set, get) => ({
      connections: [],
      currentConnection: null,
      isLoading: false,
      error: null,

      fetchConnections: async (params) => {
        set({ isLoading: true, error: null })
        try {
          const connections = await connectionsApi.listConnections(params)
          set({ 
            connections,
            isLoading: false 
          })
        } catch (error) {
          console.error('Error fetching connections:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to fetch connections',
            isLoading: false 
          })
        }
      },

      fetchConnection: async (connectionId) => {
        set({ isLoading: true, error: null })
        try {
          const connection = await connectionsApi.getConnection(connectionId)
          set((state) => ({
            connections: state.connections.some(c => c.id === connectionId)
              ? state.connections.map(c => c.id === connectionId ? connection : c)
              : [...state.connections, connection],
            currentConnection: connection,
            isLoading: false,
          }))
          return connection
        } catch (error) {
          console.error('Error fetching connection:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to fetch connection',
            isLoading: false 
          })
          throw error
        }
      },

      createConnection: async (data) => {
        set({ isLoading: true, error: null })
        try {
          const connection = await connectionsApi.createConnection(data)
          set((state) => ({
            connections: [...state.connections, connection],
            currentConnection: connection, // Set as current
            isLoading: false,
          }))
          return connection
        } catch (error) {
          console.error('Error creating connection:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to create connection',
            isLoading: false 
          })
          throw error
        }
      },

      updateConnection: async (connectionId, updates) => {
        set({ isLoading: true, error: null })
        try {
          const connection = await connectionsApi.updateConnection(connectionId, updates)
          set((state) => ({
            connections: state.connections.map((c) =>
              c.id === connectionId ? connection : c
            ),
            currentConnection: state.currentConnection?.id === connectionId
              ? connection
              : state.currentConnection,
            isLoading: false,
          }))
          return connection
        } catch (error) {
          console.error('Error updating connection:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to update connection',
            isLoading: false 
          })
          throw error
        }
      },

      deleteConnection: async (connectionId) => {
        set({ isLoading: true, error: null })
        try {
          await connectionsApi.deleteConnection(connectionId)
          set((state) => ({
            connections: state.connections.filter((c) => c.id !== connectionId),
            currentConnection: state.currentConnection?.id === connectionId
              ? null
              : state.currentConnection,
            isLoading: false,
          }))
        } catch (error) {
          console.error('Error deleting connection:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to delete connection',
            isLoading: false 
          })
          throw error
        }
      },

      setCurrentConnection: (connection) => {
        set({ currentConnection: connection })
      },

      // Connection operations
      testConnection: async (connectionId) => {
        set({ isLoading: true, error: null })
        try {
          const result = await connectionsApi.testConnection(connectionId)
          // Update connection status if test was successful
          if (result.success) {
            const connection = await get().fetchConnection(connectionId)
            set({ currentConnection: connection })
          }
          set({ isLoading: false })
          return result
        } catch (error) {
          console.error('Error testing connection:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to test connection',
            isLoading: false 
          })
          throw error
        }
      },

      syncConnection: async (connectionId) => {
        set({ isLoading: true, error: null })
        try {
          const result = await connectionsApi.syncConnection(connectionId)
          // Refresh connection data after sync
          await get().fetchConnection(connectionId)
          set({ isLoading: false })
          return result
        } catch (error) {
          console.error('Error syncing connection:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to sync connection',
            isLoading: false 
          })
          throw error
        }
      },

      getConnectionMetadata: async (connectionId) => {
        try {
          return await connectionsApi.getConnectionMetadata(connectionId)
        } catch (error) {
          console.error('Error getting connection metadata:', error)
          throw error
        }
      },

      getConnectionTables: async (connectionId) => {
        try {
          return await connectionsApi.getConnectionTables(connectionId)
        } catch (error) {
          console.error('Error getting connection tables:', error)
          throw error
        }
      },

      getConnectionSchemas: async (connectionId) => {
        try {
          return await connectionsApi.getConnectionSchemas(connectionId)
        } catch (error) {
          console.error('Error getting connection schemas:', error)
          throw error
        }
      },

      getConnectionStatus: async (connectionId) => {
        try {
          return await connectionsApi.getConnectionStatus(connectionId)
        } catch (error) {
          console.error('Error getting connection status:', error)
          throw error
        }
      },

      validateConnection: async (connectionId) => {
        try {
          return await connectionsApi.validateConnection(connectionId)
        } catch (error) {
          console.error('Error validating connection:', error)
          throw error
        }
      },
    }),
    {
      name: 'connection-storage',
      partialize: (state) => ({
        currentConnection: state.currentConnection,
      }),
    }
  )
)

