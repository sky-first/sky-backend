import { create } from "zustand"
import { aiApi, type PipelineResponse, type PipelineStepResponse, type ChatMessageResponse } from '@/lib/api/ai'
import { usePlanetStore } from "@/store/planet-store"
import { useSpaceStore } from "@/store/space-store"

export type PipelineStepStatus = "COMPLETED" | "PROCESSING" | "PENDING" | "ERROR"

export type PipelineStepKind =
  | "question"
  | "orchestrator"
  | "project"
  | "sql"
  | "tables"
  | "answer"

export interface PipelineStep {
  id: string
  name: string
  kind: PipelineStepKind
  status: PipelineStepStatus
  content: string
}

export interface ChatMessage {
  id: string
  type: "user" | "assistant"
  content: string
  timestamp: Date
  isActive?: boolean
}

export interface AIResponse {
  id: string
  content: string
  timestamp: Date
  isActive: boolean
}

export interface ConfigureData {
  question: string
  description: string
  instructions: string
  responseFormat: string
  creativity: number // 0-100
  length: number // 0-100
  knowledge: string[] // IDs of selected tables/files
  sqlInstructions: string
}

export interface LayoutData {
  title: string
  width: number
  height: number
  x: number
  y: number
  backgroundColor: string
  textColor: string
  borderColor: string
  borderRadius: number
  padding: number
}

interface PipelineState {
  isOpen: boolean
  currentWidgetId: string | null
  question: string
  answer: string
  steps: PipelineStep[]
  // Create tab data
  chatMessages: ChatMessage[]
  aiResponses: AIResponse[]
  // Configure tab data
  configureData: ConfigureData
  // Layout tab data
  layoutData: LayoutData | null
  // Pipeline data
  pipelineId: string | null
  isLoading: boolean
  error: string | null
  // Actions
  openForWidget: (params: { widgetId: string; question: string; answer: string }) => Promise<void>
  close: () => void
  setStepContent: (stepId: string, content: string) => void
  addChatMessage: (content: string) => Promise<void>
  addAIResponse: (content: string) => void
  setActiveResponse: (responseId: string) => void
  updateConfigureData: (updates: Partial<ConfigureData>) => void
  updateLayoutData: (updates: Partial<LayoutData>) => void
  // API Actions
  processQuery: (question: string, widgetId?: string) => Promise<void>
  executePipeline: () => Promise<void>
  getPipelineStatus: () => Promise<void>
  generateSQL: (question: string, knowledge: string[]) => Promise<string>
  generateAnswer: (question: string, knowledge?: string[]) => Promise<string>
  analyzeQuestion: (question: string, knowledge?: string[]) => Promise<void>
}

// Helper to convert API pipeline steps to store steps
const apiStepsToStoreSteps = (apiSteps: PipelineStepResponse[]): PipelineStep[] => {
  return apiSteps.map(step => ({
    id: step.id,
    name: (step as any).kind || 'unknown', // Use kind as name if name doesn't exist
    kind: (step as any).kind || 'question' as PipelineStepKind,
    status: step.status as PipelineStepStatus,
    content: (step.result ? JSON.stringify(step.result) : '') || '',
  }))
}

const defaultConfigureData: ConfigureData = {
  question: "",
  description: "",
  instructions: "",
  responseFormat: "text",
  creativity: 50,
  length: 50,
  knowledge: [],
  sqlInstructions: "",
}

export const usePipelineStore = create<PipelineState>((set, get) => ({
  isOpen: false,
  currentWidgetId: null,
  question: "",
  answer: "",
  steps: [],
  chatMessages: [],
  aiResponses: [],
  configureData: defaultConfigureData,
  layoutData: null,
  pipelineId: null,
  isLoading: false,
  error: null,
  
  openForWidget: async ({ widgetId, question, answer }) => {
    set({ isLoading: true, error: null })
    try {
      const isPersonal = usePlanetStore.getState().currentPlanet?.type === "personal"
      const spaceId = useSpaceStore.getState().currentSpace?.id
      // Process query to get initial response
      const queryResponse = await aiApi.query({
        question,
        widget_id: widgetId,
        configure_data: {
          question: get().configureData.question || question,
          description: get().configureData.description,
          instructions: get().configureData.instructions,
          response_format: get().configureData.responseFormat,
          creativity: get().configureData.creativity,
          length: get().configureData.length,
          knowledge: get().configureData.knowledge,
          sql_instructions: get().configureData.sqlInstructions,
        },
        space_id: spaceId,
        is_personal: isPersonal,
      })

      const initialMessage: ChatMessage = {
        id: `msg-${Date.now()}`,
        type: "user",
        content: question,
        timestamp: new Date(),
      }

      const initialResponse: AIResponse = {
        id: `resp-${Date.now()}`,
        content: queryResponse.answer || answer || "Processing...",
        timestamp: new Date(),
        isActive: true,
      }

      // If pipeline_id exists, fetch pipeline status
      let steps: PipelineStep[] = []
      if (queryResponse.pipeline_id) {
        try {
          const pipeline = await aiApi.getPipelineStatus(queryResponse.pipeline_id)
          steps = apiStepsToStoreSteps(pipeline.steps || [])
        } catch (err) {
          console.error('Error fetching pipeline status:', err)
          // Continue with empty steps
        }
      }

      set({
        isOpen: true,
        currentWidgetId: widgetId,
        question,
        answer: queryResponse.answer || answer,
        steps,
        chatMessages: [initialMessage],
        aiResponses: [initialResponse],
        configureData: {
          ...defaultConfigureData,
          question,
          instructions: queryResponse.answer || answer,
        },
        pipelineId: queryResponse.pipeline_id || null,
        isLoading: false,
      })
    } catch (error) {
      console.error('Error opening pipeline:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to process query',
        isLoading: false,
      })
    }
  },
  close: () =>
    set(() => ({
      isOpen: false,
      currentWidgetId: null,
      question: "",
      answer: "",
      steps: [],
      chatMessages: [],
      aiResponses: [],
      configureData: defaultConfigureData,
      layoutData: null,
      pipelineId: null,
      isLoading: false,
      error: null,
    })),
  setStepContent: (stepId, content) =>
    set((state) => ({
      steps: state.steps.map((step) =>
        step.id === stepId ? { ...step, content } : step
      ),
    })),
  addChatMessage: async (content) => {
    const state = get()
    if (!state.currentWidgetId) return

    // Add user message immediately
    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      type: "user",
      content,
      timestamp: new Date(),
    }
    set((state) => ({
      chatMessages: [...state.chatMessages, userMessage],
    }))

    try {
      // Send chat message to backend
      const response = await aiApi.sendChatMessage({
        message: content,
        widget_id: state.currentWidgetId,
        context: state.configureData,
      })

      // Add assistant response
      const assistantMessage: ChatMessage = {
        id: response.id,
        type: response.type as "user" | "assistant",
        content: response.content,
        timestamp: new Date(response.timestamp),
      }

      set((state) => ({
        chatMessages: [...state.chatMessages, assistantMessage],
      }))
    } catch (error) {
      console.error('Error sending chat message:', error)
      set({ error: error instanceof Error ? error.message : 'Failed to send message' })
    }
  },
  addAIResponse: (content) =>
    set((state) => ({
      aiResponses: state.aiResponses.map((r) => ({ ...r, isActive: false })).concat({
        id: `resp-${Date.now()}`,
        content,
        timestamp: new Date(),
        isActive: true,
      }),
    })),
  setActiveResponse: (responseId) =>
    set((state) => ({
      aiResponses: state.aiResponses.map((r) => ({
        ...r,
        isActive: r.id === responseId,
      })),
    })),
  updateConfigureData: (updates) =>
    set((state) => ({
      configureData: { ...state.configureData, ...updates },
    })),
  updateLayoutData: (updates) =>
    set((state) => ({
      layoutData: state.layoutData
        ? { ...state.layoutData, ...updates }
        : ({ ...updates } as LayoutData),
    })),

  processQuery: async (question, widgetId) => {
    set({ isLoading: true, error: null })
    try {
      const isPersonal = usePlanetStore.getState().currentPlanet?.type === "personal"
      const spaceId = useSpaceStore.getState().currentSpace?.id
      const response = await aiApi.query({
        question,
        widget_id: widgetId,
        configure_data: {
          question: get().configureData.question || question,
          description: get().configureData.description,
          instructions: get().configureData.instructions,
          response_format: get().configureData.responseFormat,
          creativity: get().configureData.creativity,
          length: get().configureData.length,
          knowledge: get().configureData.knowledge,
          sql_instructions: get().configureData.sqlInstructions,
        },
        space_id: spaceId,
        is_personal: isPersonal,
      })

      set({
        question,
        answer: response.answer || "",
        pipelineId: response.pipeline_id || null,
        isLoading: false,
      })

      // Fetch pipeline status if available
      if (response.pipeline_id) {
        await get().getPipelineStatus()
      }
    } catch (error) {
      console.error('Error processing query:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to process query',
        isLoading: false,
      })
      throw error
    }
  },

  executePipeline: async () => {
    const state = get()
    set({ isLoading: true, error: null })
    try {
      const response = await aiApi.executePipeline({
        steps: state.steps.map((step) => ({
          id: step.id,
          kind: step.kind,
          status: step.status,
          content: step.content,
        })),
      })

      set({
        pipelineId: response.id,
        isLoading: false,
      })

      // Fetch pipeline status
      await get().getPipelineStatus()
    } catch (error) {
      console.error('Error executing pipeline:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to execute pipeline',
        isLoading: false,
      })
      throw error
    }
  },

  getPipelineStatus: async () => {
    const state = get()
    if (!state.pipelineId) return

    try {
      const pipeline = await aiApi.getPipelineStatus(state.pipelineId)
      const steps = apiStepsToStoreSteps(pipeline.steps || [])

      set({
        steps,
        answer: pipeline.status === 'completed' ? (state.answer || '') : state.answer,
      })
    } catch (error) {
      console.error('Error fetching pipeline status:', error)
      // Don't set error here, just log it
    }
  },

  generateSQL: async (question, knowledge) => {
    set({ isLoading: true, error: null })
    try {
      const response = await aiApi.generateSQL({
        question,
      })
      set({ isLoading: false })
      return response.sql
    } catch (error) {
      console.error('Error generating SQL:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to generate SQL',
        isLoading: false,
      })
      throw error
    }
  },

  generateAnswer: async (question, knowledge) => {
    set({ isLoading: true, error: null })
    try {
      const response = await aiApi.generateAnswer({
        question,
        context: get().configureData,
      })
      set({ isLoading: false })
      return response.answer
    } catch (error) {
      console.error('Error generating answer:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to generate answer',
        isLoading: false,
      })
      throw error
    }
  },

  analyzeQuestion: async (question, knowledge) => {
    set({ isLoading: true, error: null })
    try {
      const response =       await aiApi.analyzeQuestion({
        question,
      })
      set({
        configureData: {
          ...get().configureData,
          question,
          // Update based on analysis if needed
        },
        isLoading: false,
      })
    } catch (error) {
      console.error('Error analyzing question:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to analyze question',
        isLoading: false,
      })
      throw error
    }
  },
}))


