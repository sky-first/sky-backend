import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { 
  templatesApi, 
  type Template, 
  type TemplateCreate, 
  type TemplateUpdate,
  type TemplateApplyRequest,
  type TemplateApplyResponse,
} from '@/lib/api/templates'

export interface TemplateStoreState {
  // UI State (existing)
  isOpen: boolean
  selectedCategory: string
  searchQuery: string
  showWhenCreatingBoard: boolean
  
  // Data State (new)
  templates: Template[]
  categories: string[]
  currentTemplate: Template | null
  isLoading: boolean
  error: string | null
  apiError: boolean // Track if API failed (for fallback)
  
  // UI Actions (existing)
  open: () => void
  close: () => void
  setSelectedCategory: (category: string) => void
  setSearchQuery: (query: string) => void
  setShowWhenCreatingBoard: (show: boolean) => void
  
  // Data Actions (new)
  fetchTemplates: (params?: {
    category?: string
    search?: string
    popular?: boolean
    skip?: number
    limit?: number
  }) => Promise<Template[]>
  fetchTemplate: (templateId: string) => Promise<Template>
  fetchCategories: () => Promise<void>
  createTemplate: (data: TemplateCreate) => Promise<Template>
  updateTemplate: (templateId: string, updates: TemplateUpdate) => Promise<Template>
  deleteTemplate: (templateId: string) => Promise<void>
  applyTemplate: (templateId: string, data: TemplateApplyRequest) => Promise<TemplateApplyResponse>
  setCurrentTemplate: (template: Template | null) => void
}

export const useTemplatesStore = create<TemplateStoreState>()(
  persist(
    (set, get) => ({
      // UI State
      isOpen: false,
      selectedCategory: 'all',
      searchQuery: '',
      showWhenCreatingBoard: true,
      
      // Data State
      templates: [],
      categories: ['all', 'analytics', 'business', 'finance', 'marketing', 'operations', 'sales'], // Default fallback categories
      currentTemplate: null,
      isLoading: false,
      error: null,
      apiError: false,
      
      // UI Actions
      open: () => set({ isOpen: true }),
      close: () => set({ isOpen: false }),
      setSelectedCategory: (category) => set({ selectedCategory: category }),
      setSearchQuery: (query) => set({ searchQuery: query }),
      setShowWhenCreatingBoard: (show) => set({ showWhenCreatingBoard: show }),
      
      // Data Actions
      fetchTemplates: async (params) => {
        set({ isLoading: true, error: null, apiError: false })
        try {
          const templates = await templatesApi.listTemplates(params)
          console.log('[TemplatesStore] ✅ Fetched templates from API:', templates.length)
          set({ 
            templates,
            isLoading: false,
            error: null,
            apiError: false
          })
          return templates
        } catch (error) {
          // Silently handle error - component will use fallback templates
          console.warn('[TemplatesStore] ⚠️ API error (using fallback templates):', error instanceof Error ? error.message : 'Unknown error')
          set({ 
            templates: [], // Clear to trigger fallback
            isLoading: false,
            error: null, // Don't show error to user, fallback will work
            apiError: true // Track that API failed
          })
          // Return empty array so component knows to use fallback
          return []
        }
      },
      
      fetchTemplate: async (templateId) => {
        set({ isLoading: true, error: null })
        try {
          const template = await templatesApi.getTemplate(templateId)
          set((state) => ({
            templates: state.templates.some(t => t.id === templateId)
              ? state.templates.map(t => t.id === templateId ? template : t)
              : [...state.templates, template],
            currentTemplate: template,
            isLoading: false,
          }))
          return template
        } catch (error) {
          console.error('Error fetching template:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to fetch template',
            isLoading: false 
          })
          throw error
        }
      },
      
      fetchCategories: async () => {
        try {
          const categories = await templatesApi.getCategories()
          // Only update if we got valid categories
          if (Array.isArray(categories) && categories.length > 0) {
            set({ categories })
          } else {
            // Keep default categories if API returns empty
            if (process.env.NODE_ENV === 'development') {
              console.log('[TemplatesStore] ℹ️ API returned empty categories, keeping defaults')
            }
          }
        } catch (error: any) {
          // Categories are optional - silently use fallback if API fails
          // Component uses hardcoded CATEGORIES anyway, so this is just for future use
          // 422 and other errors are expected for optional endpoints - don't log as warnings
          const is422 = error?.response?.status === 422;
          if (process.env.NODE_ENV === 'development' && !is422) {
            // Only log non-422 errors as warnings
            console.warn('[TemplatesStore] ⚠️ Categories API failed (using hardcoded categories):', error instanceof Error ? error.message : 'Unknown error')
          }
          // Don't update categories - keep defaults, don't set error
        }
      },
      
      createTemplate: async (data) => {
        set({ isLoading: true, error: null })
        try {
          const template = await templatesApi.createTemplate(data)
          set((state) => ({
            templates: [...state.templates, template],
            currentTemplate: template,
            isLoading: false,
          }))
          return template
        } catch (error) {
          console.error('Error creating template:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to create template',
            isLoading: false 
          })
          throw error
        }
      },
      
      updateTemplate: async (templateId, updates) => {
        set({ isLoading: true, error: null })
        try {
          const template = await templatesApi.updateTemplate(templateId, updates)
          set((state) => ({
            templates: state.templates.map((t) =>
              t.id === templateId ? template : t
            ),
            currentTemplate: state.currentTemplate?.id === templateId
              ? template
              : state.currentTemplate,
            isLoading: false,
          }))
          return template
        } catch (error) {
          console.error('Error updating template:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to update template',
            isLoading: false 
          })
          throw error
        }
      },
      
      deleteTemplate: async (templateId) => {
        set({ isLoading: true, error: null })
        try {
          await templatesApi.deleteTemplate(templateId)
          set((state) => ({
            templates: state.templates.filter((t) => t.id !== templateId),
            currentTemplate: state.currentTemplate?.id === templateId
              ? null
              : state.currentTemplate,
            isLoading: false,
          }))
        } catch (error) {
          console.error('Error deleting template:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to delete template',
            isLoading: false 
          })
          throw error
        }
      },
      
      applyTemplate: async (templateId, data) => {
        set({ isLoading: true, error: null })
        try {
          const result = await templatesApi.applyTemplate(templateId, data)
          set({ isLoading: false })
          return result
        } catch (error) {
          console.error('Error applying template:', error)
          set({ 
            error: error instanceof Error ? error.message : 'Failed to apply template',
            isLoading: false 
          })
          throw error
        }
      },
      
      setCurrentTemplate: (template) => {
        set({ currentTemplate: template })
      },
    }),
    {
      name: 'templates-storage',
      partialize: (state) => ({
        // Persist UI state
        selectedCategory: state.selectedCategory,
        searchQuery: state.searchQuery,
        showWhenCreatingBoard: state.showWhenCreatingBoard,
        // Don't persist templates data (loaded from API)
      }),
    }
  )
)
