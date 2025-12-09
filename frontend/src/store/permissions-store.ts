import { create } from 'zustand'
import {
  permissionsApi,
  type Permission,
  type ConnectionPermissionCreate,
  type PermissionUpdate,
  type PermissionValidateRequest,
  type PermissionValidateResponse,
} from '@/lib/api/permissions'

export interface PermissionsState {
  permissions: Permission[]
  isLoading: boolean
  error: string | null

  // Permissions by connection (cache)
  connectionPermissions: Record<string, Permission[]>

  // Permissions by space (cache)
  spacePermissions: Record<string, Permission[]>

  // Permissions by crew (cache)
  crewPermissions: Record<string, Permission[]>

  // Actions
  fetchConnectionPermissions: (connectionId: string) => Promise<void>
  createConnectionPermission: (
    connectionId: string,
    data: ConnectionPermissionCreate
  ) => Promise<Permission>
  updatePermission: (permissionId: string, updates: PermissionUpdate) => Promise<Permission>
  deletePermission: (permissionId: string) => Promise<void>
  fetchSpacePermissions: (spaceId: string) => Promise<void>
  fetchCrewPermissions: (crewId: string) => Promise<void>
  validatePermission: (data: PermissionValidateRequest) => Promise<PermissionValidateResponse>
}

export const usePermissionsStore = create<PermissionsState>()((set, get) => ({
  permissions: [],
  isLoading: false,
  error: null,
  connectionPermissions: {},
  spacePermissions: {},
  crewPermissions: {},

  fetchConnectionPermissions: async (connectionId) => {
    set({ isLoading: true, error: null })
    try {
      const permissions = await permissionsApi.getConnectionPermissions(connectionId)
      set((state) => ({
        connectionPermissions: {
          ...state.connectionPermissions,
          [connectionId]: permissions,
        },
        // Also update main permissions list
        permissions: [
          ...state.permissions.filter((p) => p.connection_id !== connectionId),
          ...permissions,
        ],
        isLoading: false,
      }))
    } catch (error) {
      console.error('Error fetching connection permissions:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch connection permissions',
        isLoading: false,
      })
    }
  },

  createConnectionPermission: async (connectionId, data) => {
    set({ isLoading: true, error: null })
    try {
      const permission = await permissionsApi.createConnectionPermission(connectionId, data)
      set((state) => ({
        permissions: [...state.permissions, permission],
        connectionPermissions: {
          ...state.connectionPermissions,
          [connectionId]: [...(state.connectionPermissions[connectionId] || []), permission],
        },
        // Also update space/crew caches if applicable
        spacePermissions: permission.space_id
          ? {
              ...state.spacePermissions,
              [permission.space_id]: [
                ...(state.spacePermissions[permission.space_id] || []),
                permission,
              ],
            }
          : state.spacePermissions,
        crewPermissions: permission.crew_id
          ? {
              ...state.crewPermissions,
              [permission.crew_id]: [
                ...(state.crewPermissions[permission.crew_id] || []),
                permission,
              ],
            }
          : state.crewPermissions,
        isLoading: false,
      }))
      return permission
    } catch (error) {
      console.error('Error creating connection permission:', error)
      set({
        error:
          error instanceof Error ? error.message : 'Failed to create connection permission',
        isLoading: false,
      })
      throw error
    }
  },

  updatePermission: async (permissionId, updates) => {
    set({ isLoading: true, error: null })
    try {
      const permission = await permissionsApi.updatePermission(permissionId, updates)
      set((state) => {
        const updatedPermissions = state.permissions.map((p) =>
          p.id === permissionId ? permission : p
        )

        // Update connection cache
        const connectionId = permission.connection_id
        const updatedConnectionPermissions = {
          ...state.connectionPermissions,
          [connectionId]: (state.connectionPermissions[connectionId] || []).map((p) =>
            p.id === permissionId ? permission : p
          ),
        }

        // Update space cache if applicable
        const updatedSpacePermissions = permission.space_id
          ? {
              ...state.spacePermissions,
              [permission.space_id]: (state.spacePermissions[permission.space_id] || []).map((p) =>
                p.id === permissionId ? permission : p
              ),
            }
          : state.spacePermissions

        // Update crew cache if applicable
        const updatedCrewPermissions = permission.crew_id
          ? {
              ...state.crewPermissions,
              [permission.crew_id]: (state.crewPermissions[permission.crew_id] || []).map((p) =>
                p.id === permissionId ? permission : p
              ),
            }
          : state.crewPermissions

        return {
          permissions: updatedPermissions,
          connectionPermissions: updatedConnectionPermissions,
          spacePermissions: updatedSpacePermissions,
          crewPermissions: updatedCrewPermissions,
          isLoading: false,
        }
      })
      return permission
    } catch (error) {
      console.error('Error updating permission:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to update permission',
        isLoading: false,
      })
      throw error
    }
  },

  deletePermission: async (permissionId) => {
    set({ isLoading: true, error: null })
    try {
      const permission = get().permissions.find((p) => p.id === permissionId)
      if (!permission) {
        throw new Error('Permission not found in store')
      }

      await permissionsApi.deletePermission(permissionId)

      set((state) => {
        const connectionId = permission.connection_id
        const spaceId = permission.space_id
        const crewId = permission.crew_id

        return {
          permissions: state.permissions.filter((p) => p.id !== permissionId),
          connectionPermissions: {
            ...state.connectionPermissions,
            [connectionId]: (state.connectionPermissions[connectionId] || []).filter(
              (p) => p.id !== permissionId
            ),
          },
          spacePermissions: spaceId
            ? {
                ...state.spacePermissions,
                [spaceId]: (state.spacePermissions[spaceId] || []).filter(
                  (p) => p.id !== permissionId
                ),
              }
            : state.spacePermissions,
          crewPermissions: crewId
            ? {
                ...state.crewPermissions,
                [crewId]: (state.crewPermissions[crewId] || []).filter(
                  (p) => p.id !== permissionId
                ),
              }
            : state.crewPermissions,
          isLoading: false,
        }
      })
    } catch (error) {
      console.error('Error deleting permission:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to delete permission',
        isLoading: false,
      })
      throw error
    }
  },

  fetchSpacePermissions: async (spaceId) => {
    set({ isLoading: true, error: null })
    try {
      const permissions = await permissionsApi.getSpacePermissions(spaceId)
      set((state) => ({
        spacePermissions: {
          ...state.spacePermissions,
          [spaceId]: permissions,
        },
        // Also update main permissions list
        permissions: [
          ...state.permissions.filter((p) => p.space_id !== spaceId),
          ...permissions,
        ],
        isLoading: false,
      }))
    } catch (error) {
      console.error('Error fetching space permissions:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch space permissions',
        isLoading: false,
      })
    }
  },

  fetchCrewPermissions: async (crewId) => {
    set({ isLoading: true, error: null })
    try {
      const permissions = await permissionsApi.getCrewPermissions(crewId)
      set((state) => ({
        crewPermissions: {
          ...state.crewPermissions,
          [crewId]: permissions,
        },
        // Also update main permissions list
        permissions: [
          ...state.permissions.filter((p) => p.crew_id !== crewId),
          ...permissions,
        ],
        isLoading: false,
      }))
    } catch (error) {
      console.error('Error fetching crew permissions:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch crew permissions',
        isLoading: false,
      })
    }
  },

  validatePermission: async (data) => {
    set({ isLoading: true, error: null })
    try {
      const result = await permissionsApi.validatePermission(data)
      set({ isLoading: false })
      return result
    } catch (error) {
      console.error('Error validating permission:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to validate permission',
        isLoading: false,
      })
      throw error
    }
  },
}))

