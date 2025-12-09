import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import {
  settingsApi,
  type Settings,
  type SettingsUpdate,
  type DataCatalogSettings,
  type SpacesSettings,
  type CrewsSettings,
  type UsersSettings,
  type PermissionsSettings,
  type APIKey,
  type APIKeyCreate,
  type APIKeyCreateResponse,
  type Integration,
  type IntegrationCreate,
  type IntegrationUpdate,
} from '@/lib/api/settings'

// UI State (for settings dialog)
interface SettingsUIState {
  isOpen: boolean
  selectedCategory: string
  searchQuery: string
  open: () => void
  close: () => void
  setSelectedCategory: (category: string) => void
  setSearchQuery: (query: string) => void
}

// Data State (for settings data from API)
interface SettingsDataState {
  // User settings
  settings: Settings | null
  isLoading: boolean
  error: string | null

  // Configuration settings (cached)
  dataCatalogSettings: DataCatalogSettings | null
  spacesSettings: SpacesSettings | null
  crewsSettings: CrewsSettings | null
  usersSettings: UsersSettings | null
  permissionsSettings: PermissionsSettings | null

  // API Keys
  apiKeys: APIKey[]

  // Integrations
  integrations: Integration[]

  // Actions
  fetchSettings: () => Promise<void>
  updateSettings: (data: SettingsUpdate) => Promise<Settings>
  fetchDataCatalogSettings: () => Promise<void>
  fetchSpacesSettings: () => Promise<void>
  fetchCrewsSettings: () => Promise<void>
  fetchUsersSettings: () => Promise<void>
  fetchPermissionsSettings: () => Promise<void>
  fetchAPIKeys: () => Promise<void>
  createAPIKey: (data: APIKeyCreate) => Promise<APIKeyCreateResponse>
  deleteAPIKey: (apiKeyId: string) => Promise<void>
  fetchIntegrations: () => Promise<void>
  createIntegration: (data: IntegrationCreate) => Promise<Integration>
  updateIntegration: (integrationId: string, data: IntegrationUpdate) => Promise<Integration>
  deleteIntegration: (integrationId: string) => Promise<void>
}

// Combined store
export interface SettingsStore extends SettingsUIState, SettingsDataState {}

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set, get) => ({
      // UI State
      isOpen: false,
      selectedCategory: 'data-catalog',
      searchQuery: '',
      open: () => set({ isOpen: true }),
      close: () => set({ isOpen: false }),
      setSelectedCategory: (category) => set({ selectedCategory: category }),
      setSearchQuery: (query) => set({ searchQuery: query }),

      // Data State
      settings: null,
      isLoading: false,
      error: null,
      dataCatalogSettings: null,
      spacesSettings: null,
      crewsSettings: null,
      usersSettings: null,
      permissionsSettings: null,
      apiKeys: [],
      integrations: [],

      fetchSettings: async () => {
        set({ isLoading: true, error: null })
        try {
          const settings = await settingsApi.getSettings()
          set({ settings, isLoading: false })
        } catch (error) {
          console.error('Error fetching settings:', error)
          set({
            error: error instanceof Error ? error.message : 'Failed to fetch settings',
            isLoading: false,
          })
        }
      },

      updateSettings: async (data) => {
        set({ isLoading: true, error: null })
        try {
          const settings = await settingsApi.updateSettings(data)
          set({ settings, isLoading: false })
          return settings
        } catch (error) {
          console.error('Error updating settings:', error)
          set({
            error: error instanceof Error ? error.message : 'Failed to update settings',
            isLoading: false,
          })
          throw error
        }
      },

      fetchDataCatalogSettings: async () => {
        set({ isLoading: true, error: null })
        try {
          const settings = await settingsApi.getDataCatalogSettings()
          set({ dataCatalogSettings: settings, isLoading: false })
        } catch (error) {
          console.error('Error fetching data catalog settings:', error)
          set({
            error:
              error instanceof Error
                ? error.message
                : 'Failed to fetch data catalog settings',
            isLoading: false,
          })
        }
      },

      fetchSpacesSettings: async () => {
        set({ isLoading: true, error: null })
        try {
          const settings = await settingsApi.getSpacesSettings()
          set({ spacesSettings: settings, isLoading: false })
        } catch (error) {
          console.error('Error fetching spaces settings:', error)
          set({
            error:
              error instanceof Error ? error.message : 'Failed to fetch spaces settings',
            isLoading: false,
          })
        }
      },

      fetchCrewsSettings: async () => {
        set({ isLoading: true, error: null })
        try {
          const settings = await settingsApi.getCrewsSettings()
          set({ crewsSettings: settings, isLoading: false })
        } catch (error) {
          console.error('Error fetching crews settings:', error)
          set({
            error:
              error instanceof Error ? error.message : 'Failed to fetch crews settings',
            isLoading: false,
          })
        }
      },

      fetchUsersSettings: async () => {
        set({ isLoading: true, error: null })
        try {
          const settings = await settingsApi.getUsersSettings()
          set({ usersSettings: settings, isLoading: false })
        } catch (error) {
          console.error('Error fetching users settings:', error)
          set({
            error:
              error instanceof Error ? error.message : 'Failed to fetch users settings',
            isLoading: false,
          })
        }
      },

      fetchPermissionsSettings: async () => {
        set({ isLoading: true, error: null })
        try {
          const settings = await settingsApi.getPermissionsSettings()
          set({ permissionsSettings: settings, isLoading: false })
        } catch (error) {
          console.error('Error fetching permissions settings:', error)
          set({
            error:
              error instanceof Error
                ? error.message
                : 'Failed to fetch permissions settings',
            isLoading: false,
          })
        }
      },

      fetchAPIKeys: async () => {
        set({ isLoading: true, error: null })
        try {
          const apiKeys = await settingsApi.getAPIKeys()
          set({ apiKeys, isLoading: false })
        } catch (error) {
          console.error('Error fetching API keys:', error)
          set({
            error: error instanceof Error ? error.message : 'Failed to fetch API keys',
            isLoading: false,
          })
        }
      },

      createAPIKey: async (data) => {
        set({ isLoading: true, error: null })
        try {
          const apiKey = await settingsApi.createAPIKey(data)
          set((state) => ({
            apiKeys: [...state.apiKeys, apiKey],
            isLoading: false,
          }))
          return apiKey
        } catch (error) {
          console.error('Error creating API key:', error)
          set({
            error: error instanceof Error ? error.message : 'Failed to create API key',
            isLoading: false,
          })
          throw error
        }
      },

      deleteAPIKey: async (apiKeyId) => {
        set({ isLoading: true, error: null })
        try {
          await settingsApi.deleteAPIKey(apiKeyId)
          set((state) => ({
            apiKeys: state.apiKeys.filter((key) => key.id !== apiKeyId),
            isLoading: false,
          }))
        } catch (error) {
          console.error('Error deleting API key:', error)
          set({
            error: error instanceof Error ? error.message : 'Failed to delete API key',
            isLoading: false,
          })
          throw error
        }
      },

      fetchIntegrations: async () => {
        set({ isLoading: true, error: null })
        try {
          const integrations = await settingsApi.getIntegrations()
          set({ integrations, isLoading: false })
        } catch (error) {
          console.error('Error fetching integrations:', error)
          set({
            error:
              error instanceof Error ? error.message : 'Failed to fetch integrations',
            isLoading: false,
          })
        }
      },

      createIntegration: async (data) => {
        set({ isLoading: true, error: null })
        try {
          const integration = await settingsApi.createIntegration(data)
          set((state) => ({
            integrations: [...state.integrations, integration],
            isLoading: false,
          }))
          return integration
        } catch (error) {
          console.error('Error creating integration:', error)
          set({
            error:
              error instanceof Error ? error.message : 'Failed to create integration',
            isLoading: false,
          })
          throw error
        }
      },

      updateIntegration: async (integrationId, data) => {
        set({ isLoading: true, error: null })
        try {
          const integration = await settingsApi.updateIntegration(integrationId, data)
          set((state) => ({
            integrations: state.integrations.map((i) =>
              i.id === integrationId ? integration : i
            ),
            isLoading: false,
          }))
          return integration
        } catch (error) {
          console.error('Error updating integration:', error)
          set({
            error:
              error instanceof Error ? error.message : 'Failed to update integration',
            isLoading: false,
          })
          throw error
        }
      },

      deleteIntegration: async (integrationId) => {
        set({ isLoading: true, error: null })
        try {
          await settingsApi.deleteIntegration(integrationId)
          set((state) => ({
            integrations: state.integrations.filter((i) => i.id !== integrationId),
            isLoading: false,
          }))
        } catch (error) {
          console.error('Error deleting integration:', error)
          set({
            error:
              error instanceof Error ? error.message : 'Failed to delete integration',
            isLoading: false,
          })
          throw error
        }
      },
    }),
    {
      name: 'settings-storage',
      partialize: (state) => ({
        // Only persist UI state and user settings
        isOpen: state.isOpen,
        selectedCategory: state.selectedCategory,
        settings: state.settings,
      }),
    }
  )
)
