"use client"

import { useState, useEffect, useRef } from "react"
import { useRouter } from "next/navigation"
import { useWidgetStore } from "@/store/widget-store"
import { useCanvasStore } from "@/store/canvas-store"
import { useAIChatboxStore } from "@/store/ai-chatbox-store"
import { Send, Mic, X, MessageSquare, Database, Settings, FileCode, Maximize2, Minimize2, Copy, ThumbsUp, ThumbsDown, Share2, RefreshCw, Sparkles, BarChart3, PieChart, TrendingUp, Table, Activity, Star, FileText, File, FileJson, ChevronDown, Loader2, Trash2, Users, LayoutGrid } from "lucide-react"
import { motion, AnimatePresence } from "framer-motion"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Badge } from "@/components/ui/badge"
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu"
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import { useFilesStore } from "@/store/files-store"
import { datasetsApi } from "@/lib/api/datasets"
import { aiApi, AIQueryResponse, type ChatBootstrapResponse, type ChatBootstrapSuggestion } from "@/lib/api/ai"
import { dashboardsApi, type DashboardAIPlanResponse } from "@/lib/api/dashboards"
import { useSpaceStore } from "@/store/space-store"
import { connectionsApi } from "@/lib/api/connections"
import { usePlanetStore } from "@/store/planet-store"

interface ChatMessage {
    id: string
    type: "user" | "assistant"
    content: string
    timestamp: Date
}

type MainTab = "chat" | "data" | "configure" | "pipeline"

export function AISearchBar() {
    const router = useRouter()
    const [question, setQuestion] = useState("")
    const [isExpanded, setIsExpanded] = useState(false)
    const [isMaximized, setIsMaximized] = useState(false)
    const [hasMessages, setHasMessages] = useState(false)
    const [showScrollbar, setShowScrollbar] = useState(false)
    const [openWidgetMenu, setOpenWidgetMenu] = useState<string | null>(null)
    const [mainTab, setMainTab] = useState<MainTab>("chat")
    const [flyingComet, setFlyingComet] = useState<{
        messageId: string
        startPos: { x: number; y: number }
        endPos: { x: number; y: number }
        widgetType: string
        widgetData: any
        isLanding?: boolean
        movementAngle?: number
    } | null>(null)
    const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
    const [chatBootstrap, setChatBootstrap] = useState<ChatBootstrapResponse | null>(null)
    const [isLoadingBootstrap, setIsLoadingBootstrap] = useState(false)
    const [bootstrapError, setBootstrapError] = useState<string | null>(null)
    const [dashboardGoal, setDashboardGoal] = useState("Billing overview")
    const [isBuildingDashboard, setIsBuildingDashboard] = useState(false)
    const [dashboardBuildProgress, setDashboardBuildProgress] = useState<{ done: number; total: number } | null>(null)
    const [dashboardAiError, setDashboardAiError] = useState<string | null>(null)
    const DASHBOARD_MAX_WIDGETS = 8

    const getErrorMessage = (err: unknown): string => {
        if (err instanceof Error) return err.message
        if (typeof err === "string") return err
        return "Something went wrong."
    }
    const [currentWidgetId, setCurrentWidgetId] = useState<string | null>(null)
    const [configureData, setConfigureData] = useState({
        question: "",
        description: "",
        instructions: "",
        responseFormat: "text",
        creativity: 50,
        length: 50,
        knowledge: [] as string[],
        sqlInstructions: "",
    })
    const [finalSQL, setFinalSQL] = useState("-- Select datasets to generate SQL")
    const [uploadingFile, setUploadingFile] = useState<string | null>(null)
    const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({})
    const [uploadedFiles, setUploadedFiles] = useState<Array<{id: string, name: string, type: 'csv' | 'excel' | 'json'}>>([])
    const [removedItems, setRemovedItems] = useState<Set<string>>(new Set())
    const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<{id: string, name: string, type: 'table' | 'file'} | null>(null)
    
    // Real connection tables data
    const [connectionTables, setConnectionTables] = useState<Array<{
        id: string
        connectionId: string
        connectionName: string
        name: string
        schema?: string
        fullName: string
        type: 'table' | 'view'
    }>>([])
    const [isLoadingTables, setIsLoadingTables] = useState(false)
    
    // Dataset metadata - will be populated from real API calls
    const datasetMetadata: Record<string, { spaces: string[]; crews: string[] }> = {}

    // Helper function to render origin info as clean text with tooltips (minimalist style)
    const renderOriginBadges = (datasetId: string) => {
        const metadata = datasetMetadata[datasetId]
        if (!metadata || (metadata.spaces.length === 0 && metadata.crews.length === 0)) {
            return null
        }

        return (
            <div className="flex items-center gap-1.5">
                {metadata.spaces.length > 0 && (
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <span className="text-[10px] text-blue-600/70 dark:text-blue-400/70 hover:text-blue-600 dark:hover:text-blue-400 cursor-help transition-colors">
                                Spaces: {metadata.spaces.length}
                            </span>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs max-w-xs">
                            <div className="space-y-1.5">
                                <div className="font-semibold text-blue-700 dark:text-blue-300">Spaces:</div>
                                <ul className="list-none space-y-0.5">
                                    {metadata.spaces.map((space, idx) => (
                                        <li key={idx} className="text-muted-foreground">{space}</li>
                                    ))}
                                </ul>
                            </div>
                        </TooltipContent>
                    </Tooltip>
                )}
                {metadata.crews.length > 0 && (
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <span className="text-[10px] text-purple-600/70 dark:text-purple-400/70 hover:text-purple-600 dark:hover:text-purple-400 cursor-help transition-colors">
                                Crews: {metadata.crews.length}
                            </span>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs max-w-xs">
                            <div className="space-y-1.5">
                                <div className="font-semibold text-purple-700 dark:text-purple-300">Crews:</div>
                                <ul className="list-none space-y-0.5">
                                    {metadata.crews.map((crew, idx) => (
                                        <li key={idx} className="text-muted-foreground">{crew}</li>
                                    ))}
                                </ul>
                            </div>
                        </TooltipContent>
                    </Tooltip>
                )}
            </div>
        )
    }
    const chatEndRef = useRef<HTMLDivElement>(null)
    const chatContainerRef = useRef<HTMLDivElement>(null)
    const expandedInputRef = useRef<HTMLInputElement>(null)
    const compactInputRef = useRef<HTMLInputElement>(null)
    const messageRefs = useRef<Record<string, HTMLDivElement | null>>({})
    const csvInputRef = useRef<HTMLInputElement>(null)
    const excelInputRef = useRef<HTMLInputElement>(null)
    const jsonInputRef = useRef<HTMLInputElement>(null)
    
    const { uploadCSV, uploadExcel, uploadFile, error: uploadError } = useFilesStore()
    
    const { addWidget, widgets, updateWidget, addPendingWidget, removePendingWidget, pendingWidgets } = useWidgetStore()
    const { getViewportCenter, snapPosition, findVisiblePositionInViewport, findNextGridPosition } = useCanvasStore()
    const { shouldOpen, widgetId, initialQuestion, initialAnswer, close } = useAIChatboxStore()
    const { currentSpace } = useSpaceStore()
    const { currentPlanet } = usePlanetStore()
    const widget = currentWidgetId ? widgets.find((w) => w.id === currentWidgetId) : null
    const [isProcessingQuery, setIsProcessingQuery] = useState(false)
    const isPersonalMode = currentPlanet?.type === "personal"

    const extractSourcesFromSql = (sql?: string): string[] => {
        if (!sql || typeof sql !== "string") return []
        // Capture identifiers after FROM/JOIN. Covers BQ (dataset.table) and quoted/backticked identifiers.
        const re = /\b(from|join)\s+([`"[\]]?)([a-zA-Z0-9_.-]+)\2/gi
        const out: string[] = []
        let m: RegExpExecArray | null
        while ((m = re.exec(sql))) {
            const ident = (m[3] || "").trim()
            if (ident) out.push(ident)
        }
        return Array.from(new Set(out))
    }

    const physicalToLogicalTable = (name: string): string => {
        const raw = String(name || "").trim()
        const last = raw.split(".").pop() || raw
        // common BQ naming in this project
        let s = last
        s = s.replace(/^silver_/, "")
        s = s.replace(/_enriquecido$/i, "")
        s = s.replace(/_enriched$/i, "")
        return s
    }

    const usedTablesForWidget: string[] = (() => {
        const d: any = widget?.data || {}
        const sqlLogicalTables = extractSourcesFromSql(d?.sql).map(physicalToLogicalTable).filter(Boolean)
        const sqlLogicalSet = new Set(sqlLogicalTables)

        const sanitize = (arr: string[]): string[] => {
            const cleaned = arr.map(String).map((s) => s.trim()).filter(Boolean)
            const uniq = Array.from(new Set(cleaned))
            // If we have table names from SQL, keep only those (prevents showing columns like customer_id).
            if (sqlLogicalSet.size > 0) {
                const filtered = uniq.filter((t) => sqlLogicalSet.has(t))
                if (filtered.length > 0) return filtered
            }
            return uniq
        }

        // Prefer explicit used_tables (logical) when available.
        if (Array.isArray(d?.used_tables) && d.used_tables.length > 0) {
            return sanitize(d.used_tables)
        }
        const chosen = d?.chosen_datasets
        if (Array.isArray(chosen) && chosen.length > 0) return sanitize(chosen)
        if (typeof d?.chosen_table === "string" && d.chosen_table) return sanitize([String(d.chosen_table)])
        // Next best: parse logical table names from the question (backticked identifiers).
        if (typeof d?.question === "string" && d.question.includes("`")) {
            const matches = Array.from(d.question.matchAll(/`([^`]+)`/g)).map((m: any) => String(m?.[1] || "").trim()).filter(Boolean)
            if (matches.length > 0) return sanitize(matches)
        }
        // Fallback: infer logical names from SQL sources (last segment after '.')
        return sanitize(sqlLogicalTables)
    })()

    const usedDatasetsFromSql: string[] = (() => {
        const d: any = widget?.data || {}
        return extractSourcesFromSql(d?.sql)
    })()

    const usedColumnsForWidget: string[] = (() => {
        const d: any = widget?.data || {}
        const rows =
            (Array.isArray(d?.data) ? d.data : null) ??
            (Array.isArray(d?.data_sample) ? d.data_sample : null) ??
            []
        if (Array.isArray(rows) && rows.length > 0 && rows[0] && typeof rows[0] === "object") {
            return Object.keys(rows[0] as Record<string, unknown>)
        }
        // Fallback for some chart widgets where we keep mapping keys.
        if (d?.mapping && typeof d.mapping === "object") {
            const maybe = Object.values(d.mapping).flatMap((v: any) =>
                typeof v === "string" ? [v] : Array.isArray(v) ? v : []
            )
            return Array.from(new Set(maybe.map(String).map((s) => s.trim()).filter(Boolean)))
        }
        return []
    })()

    // Fetch greeting + suggestions when opening a new chat session (Personal mode only).
    useEffect(() => {
        const shouldFetch =
            isExpanded &&
            mainTab === "chat" &&
            isPersonalMode &&
            chatMessages.length === 0

        if (!shouldFetch) return
        if (isLoadingBootstrap) return
        if (chatBootstrap) return

        let cancelled = false
        ;(async () => {
            try {
                setBootstrapError(null)
                setIsLoadingBootstrap(true)
                const resp = await aiApi.chatBootstrap({
                    // Personal mode shouldn't require an explicit space selection.
                    // Backend will resolve a suitable space context when omitted.
                    space_id: currentSpace?.id,
                    // Keep chat bootstrap in English for now.
                    language: "en",
                    max_suggestions: 4,
                })
                if (cancelled) return
                setChatBootstrap(resp)
            } catch (e) {
                if (cancelled) return
                setBootstrapError(e instanceof Error ? e.message : "Failed to load suggestions")
                setChatBootstrap(null)
            } finally {
                // Always clear the loading flag. Even if the effect is "cancelled" due to
                // a dependency change/unmount, leaving this true will stick the UI in
                // "Loading suggestions...".
                setIsLoadingBootstrap(false)
            }
        })()

        return () => {
            cancelled = true
        }
    }, [isExpanded, mainTab, isPersonalMode, chatMessages.length, currentSpace?.id])

    const loadingMessages = [
        "Analyzing your request",
        "Reviewing connected data sources",
        "Preparing your insights",
    ] as const
    const [loadingStepIndex, setLoadingStepIndex] = useState(0)

    // React to store changes - open chatbox with widget information
    useEffect(() => {
        if (shouldOpen && widgetId && initialQuestion !== null) {
            // Set widget ID
            setCurrentWidgetId(widgetId)
            
            // Expand chatbox
            setIsExpanded(true)
            setMainTab("chat")
            
            // Pre-fill with widget information if available
            if (initialQuestion) {
                // Add question as user message
                const userMessage: ChatMessage = {
                    id: `msg-${Date.now()}`,
                    type: "user",
                    content: initialQuestion,
                    timestamp: new Date(),
                }
                
                // Add answer as assistant message if available
                const messages: ChatMessage[] = [userMessage]
                if (initialAnswer) {
                    const aiMessage: ChatMessage = {
                        id: `ai-${Date.now()}`,
                        type: "assistant",
                        content: initialAnswer,
                        timestamp: new Date(),
                    }
                    messages.push(aiMessage)
                    setHasMessages(true)
                }
                
                setChatMessages(messages)
            }
            
            // If this widget already has a generated SQL, reflect it in the Pipeline tab UI.
            const w = widgets.find((ww) => ww.id === widgetId)
            const existingSql = (w as any)?.data?.sql
            if (typeof existingSql === "string" && existingSql.trim()) {
                setFinalSQL(existingSql)
            }

            // Clear the store flag
            close()
            
            // Scroll to bottom after messages are set and component is rendered
            setTimeout(() => {
                if (chatEndRef.current) {
                    chatEndRef.current.scrollIntoView({ behavior: "smooth" })
                }
                // Also try scrolling the container directly
                if (chatContainerRef.current) {
                    chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
                }
                // Focus input after expansion
                expandedInputRef.current?.focus()
            }, 400)
        }
    }, [shouldOpen, widgetId, initialQuestion, initialAnswer, close, widgets])

    // Rotate loading messages while AI is processing
    useEffect(() => {
        if (!isProcessingQuery) {
            setLoadingStepIndex(0)
            return
        }

        let currentIndex = 0
        setLoadingStepIndex(0)

        const interval = setInterval(() => {
            currentIndex = (currentIndex + 1) % loadingMessages.length
            setLoadingStepIndex(currentIndex)
        }, 2200)

        return () => clearInterval(interval)
    }, [isProcessingQuery, loadingMessages.length])

    // Auto-scroll chat to bottom when messages change or chatbox expands
    useEffect(() => {
        if (isExpanded && mainTab === "chat") {
            // Use a small delay to ensure DOM is updated
            const timeoutId = setTimeout(() => {
                if (chatEndRef.current) {
                    chatEndRef.current.scrollIntoView({ behavior: "smooth" })
                }
                // Also scroll container directly as fallback
                if (chatContainerRef.current) {
                    chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
                }
            }, 150)
            
            return () => clearTimeout(timeoutId)
        }
    }, [chatMessages, isExpanded, mainTab])
    
    // Additional effect to scroll when chatbox is expanded (for direct clicks)
    useEffect(() => {
        if (isExpanded && mainTab === "chat" && chatMessages.length > 0) {
            // Scroll to bottom when chatbox is expanded with existing messages
            const timeoutId = setTimeout(() => {
                if (chatEndRef.current) {
                    chatEndRef.current.scrollIntoView({ behavior: "smooth" })
                }
                if (chatContainerRef.current) {
                    chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
                }
            }, 200)
            
            return () => clearTimeout(timeoutId)
        }
    }, [isExpanded])

    // Close widget menu when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (openWidgetMenu && !(event.target as Element).closest('[data-widget-menu]')) {
                setOpenWidgetMenu(null)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [openWidgetMenu])

    // Load table details for tables used by AI (only when needed)
    useEffect(() => {
        const loadTableDetails = async () => {
            // Get all tables used by AI from chat messages
            const aiUsedTables = Array.from(new Set(
                chatMessages
                    .filter(msg => msg.type === "assistant")
                    .flatMap(msg => {
                        const datasets = (msg as any).responseData?.chosen_datasets || [];
                        const table = (msg as any).responseData?.chosen_table;
                        return datasets.length > 0 ? datasets : (table ? [table] : []);
                    })
            ))
            
            if (aiUsedTables.length === 0) {
                setConnectionTables([])
                return
            }
            
            // Only load details if we don't have them yet
            const needsLoading = aiUsedTables.some(tableName => 
                !connectionTables.some(t => t.name === tableName || t.fullName === tableName)
            )
            
            if (!needsLoading) return
            
            setIsLoadingTables(true)
            try {
                // Get all active connections
                const connections = await connectionsApi.listConnections({ status: "active" })
                
                // Load metadata only for tables used by AI
                const foundTables: Array<{
                    id: string
                    connectionId: string
                    connectionName: string
                    name: string
                    schema?: string
                    fullName: string
                    type: 'table' | 'view'
                }> = []
                
                for (const conn of connections) {
                    try {
                        const metadata = await connectionsApi.getConnectionMetadata(conn.id)
                        if (metadata.tables && metadata.tables.length > 0) {
                            metadata.tables.forEach((table: any) => {
                                const schemaName = table.schema || table.schema_name || ''
                                const fullName = schemaName ? `${schemaName}.${table.name}` : table.name
                                
                                // Only include if this table was used by AI
                                if (aiUsedTables.includes(table.name) || aiUsedTables.includes(fullName)) {
                                    foundTables.push({
                                        id: `${conn.id}-${table.name}`,
                                        connectionId: conn.id,
                                        connectionName: conn.name,
                                        name: table.name,
                                        schema: schemaName,
                                        fullName: fullName,
                                        type: (table.name.toLowerCase().includes('view') || fullName.toLowerCase().includes('view')) ? 'view' : 'table'
                                    })
                                }
                            })
                        }
                    } catch (err) {
                        console.warn(`Failed to load metadata for connection ${conn.id}:`, err)
                    }
                }
                
                setConnectionTables(foundTables)
            } catch (error) {
                console.error('Error loading table details:', error)
            } finally {
                setIsLoadingTables(false)
            }
        }
        
        if (mainTab === "data") {
            loadTableDetails()
        }
    }, [mainTab, chatMessages, connectionTables.length])

    // Update SQL when knowledge changes
    useEffect(() => {
        if (configureData.knowledge.length > 0 && configureData.sqlInstructions) {
            const tables = configureData.knowledge.join(", ")
            setFinalSQL(`-- Generated SQL based on selected datasets: ${tables}\n${configureData.sqlInstructions}`)
        } else if (configureData.knowledge.length > 0) {
            const tables = configureData.knowledge.join(", ")
            setFinalSQL(`SELECT * FROM ${tables} LIMIT 1000;`)
        } else {
            setFinalSQL("-- Select datasets to generate SQL")
        }
    }, [configureData.knowledge, configureData.sqlInstructions])

    // Handle item deletion
    const handleDeleteClick = (id: string, name: string, type: 'table' | 'file') => {
        setItemToDelete({ id, name, type })
        setDeleteDialogOpen(true)
    }

    const handleConfirmDelete = async () => {
        if (!itemToDelete) return

        const { id, type } = itemToDelete

        try {
            // Call backend API to delete the dataset
            await datasetsApi.deleteDataset(id)

            // Add to removed items
            setRemovedItems(prev => new Set(prev).add(id))

            // Remove from knowledge
            setConfigureData({
                ...configureData,
                knowledge: configureData.knowledge.filter((k) => k !== id)
            })

            // If it's a file, also remove from uploadedFiles
            if (type === 'file') {
                setUploadedFiles(prev => prev.filter(f => f.id !== id))
            }

            // Close dialog and reset
            setDeleteDialogOpen(false)
            setItemToDelete(null)
        } catch (error) {
            console.error('Error deleting dataset:', error)
            alert(`Error deleting dataset: ${error instanceof Error ? error.message : 'Unknown error'}`)
        }
    }

    // Handle file uploads
    const handleCSVUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return

        setUploadingFile(file.name)
        try {
            const response = await uploadCSV(file, (progress) => {
                setUploadProgress(prev => ({ ...prev, [file.name]: progress }))
            })
            
            // Add file to uploaded files list
            const fileIdentifier = `file_${response.file_id}`
            setUploadedFiles(prev => [...prev, {
                id: fileIdentifier,
                name: file.name,
                type: 'csv'
            }])
            
            // Add file to knowledge list using file_id as identifier
            if (!configureData.knowledge.includes(fileIdentifier)) {
                setConfigureData({
                    ...configureData,
                    knowledge: [...configureData.knowledge, fileIdentifier]
                })
            }
        } catch (error) {
            console.error('Error uploading CSV:', error)
            alert(`Error uploading CSV: ${error instanceof Error ? error.message : 'Unknown error'}`)
        } finally {
            setUploadingFile(null)
            setUploadProgress(prev => {
                const newProgress = { ...prev }
                delete newProgress[file.name]
                return newProgress
            })
            if (csvInputRef.current) {
                csvInputRef.current.value = ''
            }
        }
    }

    const handleExcelUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return

        setUploadingFile(file.name)
        try {
            const response = await uploadExcel(file, (progress) => {
                setUploadProgress(prev => ({ ...prev, [file.name]: progress }))
            })
            
            // Add file to uploaded files list
            const fileIdentifier = `file_${response.file_id}`
            setUploadedFiles(prev => [...prev, {
                id: fileIdentifier,
                name: file.name,
                type: 'excel'
            }])
            
            // Add file to knowledge list using file_id as identifier
            if (!configureData.knowledge.includes(fileIdentifier)) {
                setConfigureData({
                    ...configureData,
                    knowledge: [...configureData.knowledge, fileIdentifier]
                })
            }
        } catch (error) {
            console.error('Error uploading Excel:', error)
            alert(`Error uploading Excel: ${error instanceof Error ? error.message : 'Unknown error'}`)
        } finally {
            setUploadingFile(null)
            setUploadProgress(prev => {
                const newProgress = { ...prev }
                delete newProgress[file.name]
                return newProgress
            })
            if (excelInputRef.current) {
                excelInputRef.current.value = ''
            }
        }
    }

    const handleJSONUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return

        setUploadingFile(file.name)
        try {
            const response = await uploadFile(file, undefined, (progress) => {
                setUploadProgress(prev => ({ ...prev, [file.name]: progress }))
            })
            
            // Add file to uploaded files list
            const fileIdentifier = `file_${response.file_id}`
            setUploadedFiles(prev => [...prev, {
                id: fileIdentifier,
                name: file.name,
                type: 'json'
            }])
            
            // Add file to knowledge list using file_id as identifier
            if (!configureData.knowledge.includes(fileIdentifier)) {
                setConfigureData({
                    ...configureData,
                    knowledge: [...configureData.knowledge, fileIdentifier]
                })
            }
        } catch (error) {
            console.error('Error uploading JSON:', error)
            alert(`Error uploading JSON: ${error instanceof Error ? error.message : 'Unknown error'}`)
        } finally {
            setUploadingFile(null)
            setUploadProgress(prev => {
                const newProgress = { ...prev }
                delete newProgress[file.name]
                return newProgress
            })
            if (jsonInputRef.current) {
                jsonInputRef.current.value = ''
            }
        }
    }

    const handleSendMessage = async (overrideText?: string) => {
        let text = (overrideText ?? question).trim()
        // Fallback for environments where programmatic typing doesn't update React state:
        // read the value directly from the input refs.
        if (!overrideText && !text) {
            const fromExpanded = expandedInputRef.current?.value ?? ""
            const fromCompact = compactInputRef.current?.value ?? ""
            text = (fromExpanded || fromCompact).trim()
        }
        if (!text || isProcessingQuery) return

        const userMessage: ChatMessage = {
            id: `msg-${Date.now()}`,
            type: "user",
            content: text,
            timestamp: new Date(),
        }

        setChatMessages(prev => [...prev, userMessage])
        const messageText = text
        setQuestion("")

        // Expand if not already expanded
        if (!isExpanded) {
            setIsExpanded(true)
        }
        
        // Mark that we have messages (for auto-expansion)
        setHasMessages(true)
        setIsProcessingQuery(true)

        try {
            // Call real AI API
            const response: AIQueryResponse = await aiApi.query({
                question: messageText,
                widget_id: currentWidgetId || undefined,
                configure_data: {
                    question: messageText,
                    knowledge: configureData.knowledge,
                    // Force textual answer format for chat responses
                    response_format: "text",
                    creativity: configureData.creativity,
                    length: configureData.length,
                    sql_instructions: configureData.sqlInstructions,
                },
                space_id: currentSpace?.id,
                is_personal: isPersonalMode,
            })

            // Create AI message with real response
            const aiMessage: ChatMessage = {
                id: `ai-${Date.now()}`,
                type: "assistant",
                content: response.answer || "No answer generated",
                timestamp: new Date(),
            }
            
            // Store response data for widget creation
            const chosenDatasets = response.chosen_datasets || (response.chosen_table ? [response.chosen_table] : [])
            
            console.log("AI Response data:", {
                chosen_table: response.chosen_table,
                chosen_datasets: response.chosen_datasets,
                final_chosen_datasets: chosenDatasets,
                answer_length: response.answer?.length
            })
            
            ;(aiMessage as any).responseData = {
                data_sample: response.data_sample,
                sql: response.sql,
                chosen_table: response.chosen_table,
                chosen_datasets: chosenDatasets,
            }

            // Update knowledge with datasets chosen by AI
            if (response.chosen_datasets && response.chosen_datasets.length > 0) {
                setConfigureData(prev => ({
                    ...prev,
                    knowledge: [...new Set([...prev.knowledge, ...response.chosen_datasets!])],
                }))
            } else if (response.chosen_table) {
                setConfigureData(prev => ({
                    ...prev,
                    knowledge: [...new Set([...prev.knowledge, response.chosen_table!])],
                }))
            }

            setChatMessages(prev => [...prev, aiMessage])
        } catch (error) {
            console.error("Error calling AI API:", error)
            const errorMessage: ChatMessage = {
                id: `ai-error-${Date.now()}`,
                type: "assistant",
                content: `Error: ${error instanceof Error ? error.message : "Failed to get AI response"}`,
                timestamp: new Date(),
            }
            setChatMessages(prev => [...prev, errorMessage])
        } finally {
            setIsProcessingQuery(false)
        }
    }

    const handleSubmitQuestion = async (e: React.FormEvent) => {
        e.preventDefault()
        await handleSendMessage()
    }

    const handleClose = () => {
        setIsExpanded(false)
        setIsMaximized(false)
        setHasMessages(false)
        // Treat close as "new chat" next time it opens.
        setChatMessages([])
        setChatBootstrap(null)
        setBootstrapError(null)
    }

    const handleCompactInputClick = () => {
        // Focus on compact input immediately when clicked
        compactInputRef.current?.focus()
        
        setIsExpanded(true)
        // Focus on expanded input after expansion animation completes
        setTimeout(() => {
            expandedInputRef.current?.focus()
            // Scroll to bottom to show last message
            if (chatEndRef.current) {
                chatEndRef.current.scrollIntoView({ behavior: "smooth" })
            }
            // Also scroll container directly as fallback
            if (chatContainerRef.current) {
                chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
            }
        }, 300)
    }

    const handleToggleMaximize = () => {
        setIsMaximized(prev => !prev)
    }


    const handleCreateWidgetWithAnimation = async (
        messageId: string,
        messageElement: HTMLElement,
        widgetType: 'kpi' | 'chart' | 'table',
        widgetData: any
    ) => {
        // Clear any existing comet animation first
        setFlyingComet(null)
        
        // Capture start position BEFORE closing chatbox (comet icon position)
        // Use a small delay to ensure DOM is stable
        await new Promise(resolve => setTimeout(resolve, 10))
        const messageRect = messageElement.getBoundingClientRect()
        const startPos = {
            x: messageRect.right - 20, // Position of comet icon
            y: messageRect.top + 10
        }

        // Get current canvas state for animation calculations
        const { position: canvasPosition, scale } = useCanvasStore.getState()
        
        // Widget dimensions
        const widgetSize = widgetData.size || { width: 250, height: 120 }
        const widgetWidth = widgetSize.width
        const widgetHeight = widgetSize.height
        
        // Combine existing widgets with pending widgets for position calculation
        const allWidgets = [
            ...widgets.map(w => ({ position: w.position, size: w.size })),
            ...pendingWidgets
        ]
        
        // Use grid positioning for initial placement
        const finalPosition = findNextGridPosition(
            { width: widgetWidth, height: widgetHeight },
            allWidgets
        )
        
        // Add this widget to pending widgets immediately
        addPendingWidget(finalPosition, widgetSize)
        
        // Calculate widget center in canvas coordinates
        const widgetCenterX = finalPosition.x + widgetSize.width / 2
        const widgetCenterY = finalPosition.y + widgetSize.height / 2
        
        // Calculate end position (widget center) in screen coordinates for animation
        const endPos = {
            x: widgetCenterX * scale + canvasPosition.x,
            y: widgetCenterY * scale + canvasPosition.y
        }

        // Calculate movement angle for comet rotation (comet tail should point opposite to movement)
        const dx = endPos.x - startPos.x
        const dy = endPos.y - startPos.y
        const movementAngle = Math.atan2(dy, dx) * 180 / Math.PI

        // Close menu first
        setOpenWidgetMenu(null)

        // Close chatbox to initial state (before it was clicked)
        setIsExpanded(false)
        setIsMaximized(false)
        setHasMessages(false)

        // Wait for chatbox closing animation to complete (0.3s)
        setTimeout(() => {
            // Ensure we have fresh canvas state when starting animation
            const currentCanvasState = useCanvasStore.getState()
            const currentEndPos = {
                x: widgetCenterX * currentCanvasState.scale + currentCanvasState.position.x,
                y: widgetCenterY * currentCanvasState.scale + currentCanvasState.position.y
            }
            
            // Recalculate angle with current positions
            const currentDx = currentEndPos.x - startPos.x
            const currentDy = currentEndPos.y - startPos.y
            const currentMovementAngle = Math.atan2(currentDy, currentDx) * 180 / Math.PI
            
            // Start comet animation after chatbox is closed with fresh values
            setFlyingComet({
                messageId: `${messageId}-${Date.now()}`, // Unique ID for each animation
                startPos,
                endPos: currentEndPos,
                widgetType,
                widgetData: { ...widgetData, position: finalPosition },
                isLanding: false,
                movementAngle: currentMovementAngle
            })

            // After comet reaches destination, create widget immediately and show landing animation
                    setTimeout(async () => {
                        try {
                    // Remove from pending widgets before creating
                    removePendingWidget(finalPosition, widgetSize)
                    
                    // Ensure all required fields are present with defaults
                    const widgetToCreate = {
                        type: widgetType,
                        title: widgetData.title || 'AI Response',
                        size: widgetData.size || widgetSize,
                        position: finalPosition,
                        data: widgetData.data || {}
                    }
                    
                    // Validate required fields before creating
                    if (!widgetToCreate.title || widgetToCreate.title.trim() === '') {
                        throw new Error('Widget title is required')
                    }
                    if (!widgetToCreate.size || !widgetToCreate.size.width || !widgetToCreate.size.height) {
                        throw new Error('Widget size is required')
                    }
                    if (!widgetToCreate.position || typeof widgetToCreate.position.x !== 'number' || typeof widgetToCreate.position.y !== 'number') {
                        throw new Error('Widget position is required')
                    }
                    
                    // Create widget immediately when comet arrives
                            await addWidget(widgetToCreate)
                    
                    // Start landing animation (expansion) while widget appears
                    setFlyingComet(prev => prev ? { ...prev, isLanding: true } : null)
                    
                    // Clear comet after a brief moment (widget is already visible)
                    setTimeout(() => {
                        setFlyingComet(null)
                    }, 200) // Brief fade out
        } catch (error) {
            console.error('Error creating widget:', error)
                    // Remove from pending widgets even if creation fails
                    removePendingWidget(finalPosition, widgetSize)
                    setFlyingComet(null)
        }
            }, 550) // Travel animation duration - increased for better visibility
        }, 300) // Chatbox closing animation duration
    }


    return (
        <>
            {/* Flying Comet Animation */}
            <AnimatePresence>
                {flyingComet && (
                    <motion.div
                        initial={{ 
                            x: flyingComet.startPos.x,
                            y: flyingComet.startPos.y,
                            scale: 1,
                            opacity: 1,
                            rotate: flyingComet.movementAngle ?? 0
                        }}
                        animate={flyingComet.isLanding ? {
                            x: flyingComet.endPos.x,
                            y: flyingComet.endPos.y,
                            scale: [1.2, 3, 0],
                            opacity: [1, 0.8, 0],
                            rotate: flyingComet.movementAngle ?? 0
                        } : {
                            x: flyingComet.endPos.x,
                            y: flyingComet.endPos.y,
                            scale: 1.2,
                            opacity: 1,
                            rotate: flyingComet.movementAngle ?? 0
                        }}
                        exit={{ 
                            scale: 0,
                            opacity: 0
                        }}
                        transition={flyingComet.isLanding ? {
                            duration: 0.2, // Reduced from 0.4s for faster fade out
                            ease: "easeOut",
                            times: [0, 0.5, 1]
                        } : {
                            duration: 0.55, // Travel animation duration - increased for better visibility
                            ease: "easeInOut"
                        }}
                        className="fixed pointer-events-none z-[100]"
                        style={{
                            transform: 'translate(-50%, -50%)'
                        }}
                    >
                        {/* Star visual: circle with tail */}
                        <svg
                            width="48"
                            height="48"
                            viewBox="0 0 48 48"
                            className="drop-shadow-lg"
                            style={{ filter: 'drop-shadow(0 0 12px rgba(234, 179, 8, 0.8))' }}
                        >
                            <defs>
                                <linearGradient id={`cometTail-${flyingComet.messageId}`} x1="100%" y1="50%" x2="0%" y2="50%">
                                    <stop offset="0%" stopColor="rgba(234, 179, 8, 0.9)" stopOpacity="0.9" />
                                    <stop offset="30%" stopColor="rgba(250, 204, 21, 0.6)" stopOpacity="0.6" />
                                    <stop offset="70%" stopColor="rgba(253, 224, 71, 0.3)" stopOpacity="0.3" />
                                    <stop offset="100%" stopColor="rgba(253, 224, 71, 0)" stopOpacity="0" />
                                </linearGradient>
                                <radialGradient id={`cometGlow-${flyingComet.messageId}`} cx="50%" cy="50%">
                                    <stop offset="0%" stopColor="rgb(253, 224, 71)" stopOpacity="1" />
                                    <stop offset="70%" stopColor="rgb(250, 204, 21)" stopOpacity="0.8" />
                                    <stop offset="100%" stopColor="rgb(234, 179, 8)" stopOpacity="0.4" />
                                </radialGradient>
                            </defs>
                            {/* Long tail path - pointing backwards (opposite to movement direction) */}
                            {/* Tail starts from center and extends backwards */}
                            <path
                                d="M 24 24 L 8 24"
                                stroke={`url(#cometTail-${flyingComet.messageId})`}
                                strokeWidth="4"
                                fill="none"
                                strokeLinecap="round"
                            />
                            {/* Secondary tail for depth */}
                            <path
                                d="M 24 24 L 10 24"
                                stroke={`url(#cometTail-${flyingComet.messageId})`}
                                strokeWidth="2"
                                fill="none"
                                strokeLinecap="round"
                                opacity="0.5"
                            />
                            {/* Circle (star head) - positioned at center */}
                            <circle
                                cx="24"
                                cy="24"
                                r="7"
                                fill={`url(#cometGlow-${flyingComet.messageId})`}
                            />
                            {/* Bright center */}
                            <circle
                                cx="24"
                                cy="24"
                                r="4"
                                fill="rgb(254, 240, 138)"
                            />
                            {/* Core highlight */}
                            <circle
                                cx="24"
                                cy="24"
                                r="2"
                                fill="rgb(255, 255, 255)"
                            />
                        </svg>
                    </motion.div>
                )}
            </AnimatePresence>

            <div 
                className="fixed bottom-16 left-1/2 transform -translate-x-1/2 z-10 pointer-events-auto" 
                data-tour="ai-search"
                style={{ 
                    // Garantir que sempre fique fixo na parte inferior
                    bottom: '64px'
                }}
            >
            <AnimatePresence mode="wait">
                {!isExpanded ? (
                    // Compact view - just the input bar
                    <motion.div
                        key="compact"
                        initial={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                    >
            <form
                onSubmit={handleSubmitQuestion}
                            onClick={handleCompactInputClick}
                            className="rounded-full px-6 py-3 flex items-center gap-3 min-w-[500px] max-w-[600px] border-2 border-border bg-background/95 backdrop-blur-xl shadow-lg cursor-text"
            >
                <input
                    ref={compactInputRef}
                    type="text"
                    placeholder="What you want to analyse today?"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault()
                            handleSubmitQuestion(e as any)
                        }
                    }}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    handleCompactInputClick()
                                }}
                                onFocus={() => {
                                    // When input gets focus, expand if not already expanded
                                    if (!isExpanded) {
                                        handleCompactInputClick()
                                    }
                                }}
                                className="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground outline-none text-sm font-medium cursor-text"
                />
                <button 
                    type="button"
                    className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-accent"
                    aria-label="Voice input"
                >
                    <Mic className="h-5 w-5" />
                </button>
                <button 
                    type="submit" 
                    className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-accent"
                    aria-label="Submit question"
                >
                    <Send className="h-5 w-5" />
                </button>
            </form>
                    </motion.div>
                ) : (
                    // Expanded view - chat area + input (expande para cima)
                    <motion.div
                        key="expanded"
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 20 }}
                        transition={{ duration: 0.3, ease: "easeOut" }}
                        className="bg-background/95 backdrop-blur-xl border-2 border-border rounded-2xl shadow-2xl flex flex-col"
                        style={{ 
                            width: isMaximized 
                                ? "50vw" 
                                : hasMessages 
                                    ? "660px" // 600px + 10% = 660px quando tem mensagens
                                    : "600px", // Tamanho inicial
                            maxWidth: isMaximized ? "50vw" : "90vw",
                            maxHeight: isMaximized 
                                ? "620px" 
                                : hasMessages 
                                    ? "531px" // 462px + 15% = 531px quando tem mensagens
                                    : "520px", // Aumentado para acomodar margens e pergunta adicional
                            height: "auto",
                            // Garantir que a parte inferior sempre fique fixa
                            marginBottom: 0,
                            transition: "max-height 0.3s ease-out, width 0.3s ease-out"
                        }}
                    >
                        {/* Header */}
                        <div className="px-4 py-3 border-b border-border/50 flex items-center justify-between flex-shrink-0">
                            <div className="flex items-center gap-2">
                                {/* Tab Icons */}
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={() => setMainTab("chat")}
                                            className={cn(
                                                "p-2 rounded-lg transition-colors",
                                                mainTab === "chat"
                                                    ? "bg-primary text-primary-foreground"
                                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                                            )}
                                            aria-label="Chat"
                                        >
                                            <MessageSquare className="h-4 w-4" />
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs bg-primary text-primary-foreground">
                                        Chat
                                    </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={() => setMainTab("data")}
                                            className={cn(
                                                "p-2 rounded-lg transition-colors",
                                                mainTab === "data"
                                                    ? "bg-primary text-primary-foreground"
                                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                                            )}
                                            aria-label="Data"
                                        >
                                            <Database className="h-4 w-4" />
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs bg-primary text-primary-foreground">
                                        Data
                                    </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={() => setMainTab("configure")}
                                            className={cn(
                                                "p-2 rounded-lg transition-colors",
                                                mainTab === "configure"
                                                    ? "bg-primary text-primary-foreground"
                                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                                            )}
                                            aria-label="Configure"
                                        >
                                            <Settings className="h-4 w-4" />
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs bg-primary text-primary-foreground">
                                        Configure
                                    </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={() => setMainTab("pipeline")}
                                            className={cn(
                                                "p-2 rounded-lg transition-colors",
                                                mainTab === "pipeline"
                                                    ? "bg-primary text-primary-foreground"
                                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                                            )}
                                            aria-label="Pipeline"
                                        >
                                            <FileCode className="h-4 w-4" />
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs bg-primary text-primary-foreground">
                                        Pipeline
                                    </TooltipContent>
                                </Tooltip>
                            </div>
                            <div className="flex items-center gap-1">
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={handleToggleMaximize}
                                            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-accent"
                                            aria-label={isMaximized ? "Minimize" : "Expand"}
                                        >
                                            {isMaximized ? (
                                                <Minimize2 className="h-4 w-4" />
                                            ) : (
                                                <Maximize2 className="h-4 w-4" />
                                            )}
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs bg-primary text-primary-foreground">
                                        {isMaximized ? "Minimize" : "Expand"}
                                    </TooltipContent>
                                </Tooltip>
                                <button
                                    onClick={handleClose}
                                    className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-accent"
                                    aria-label="Close chat"
                                >
                                    <X className="h-4 w-4" />
                                </button>
                            </div>
                        </div>

                        {/* Content area - changes based on selected tab */}
                        <div
                            ref={chatContainerRef}
                            onMouseEnter={() => setShowScrollbar(true)}
                            onMouseLeave={() => setShowScrollbar(false)}
                            onWheel={(e) => {
                                // Prevent canvas scroll when scrolling inside chatbox
                                e.stopPropagation()
                            }}
                            className={cn(
                                "flex-1 overflow-y-auto min-h-0",
                                "transition-all duration-200",
                                showScrollbar ? "custom-scrollbar-visible" : "custom-scrollbar-hidden"
                            )}
                            style={{ 
                                maxHeight: isMaximized 
                                    ? "520px" 
                                    : hasMessages 
                                        ? "431px" // Ajustado proporcionalmente (362px + 15% ≈ 416px, ajustado para 431px)
                                        : "343px", // 285px + 15% ≈ 328px, ajustado para 343px para manter proporção
                                transition: "max-height 0.3s ease-out"
                            }}
                        >
                            {/* CHAT TAB */}
                            {mainTab === "chat" && (
                                <div className="px-4 py-3 space-y-3">
                                    {chatMessages.length === 0 ? (
                                        <div className="space-y-2">
                                            {/* Intro text */}
                                            <div className="text-center pt-6">
                                                <p className="text-xs font-medium text-foreground">Some suggestions.</p>
                                            </div>
                                            
                                            {/* Suggestion Cards Grid 2x2 */}
                                            <div className="grid grid-cols-2 gap-3 max-w-[40%] mx-auto mb-8">
                                                {(() => {
                                                    const fallback: ChatBootstrapSuggestion[] = [
                                                        { title: "Available data", kind: "question", question: "What data do I have access to?" },
                                                        { title: "Tables", kind: "question", question: "Which tables are available in my catalog?" },
                                                        { title: "Columns", kind: "question", question: "What columns are inside the customers table?" },
                                                        { title: "Examples", kind: "question", question: "Give me examples of questions I can ask about my data." },
                                                    ]
                                                    const cards =
                                                        chatBootstrap?.suggestions?.length ? chatBootstrap.suggestions : fallback

                                                    return cards.map((suggestion, idx) => {
                                                        const kind = suggestion?.kind || "question"
                                                        const label =
                                                            kind === "action"
                                                                ? (suggestion?.title || "Action")
                                                                : (suggestion?.question || "")
                                                        return (
                                                            <Tooltip key={idx}>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={async () => {
                                                                            if (kind === "action") {
                                                                                if (isBuildingDashboard) return
                                                                                try {
                                                                                    setDashboardAiError(null)
                                                                                    setIsBuildingDashboard(true)
                                                                                    setDashboardBuildProgress(null)
                                                                                    const started = await dashboardsApi.aiBuildDashboardAsync({
                                                                                        space_id: currentSpace?.id,
                                                                                        goal: dashboardGoal,
                                                                                        language: "en",
                                                                                        max_widgets: DASHBOARD_MAX_WIDGETS,
                                                                                    })
                                                                                    const jobId = started.job_id
                                                                                    const pollStart = Date.now()
                                                                                    const poll = async () => {
                                                                                        // Poll until we have dashboard_id or error
                                                                                        while (Date.now() - pollStart < 10 * 60 * 1000) { // 10m safety
                                                                                            const st = await dashboardsApi.getDashboardBuildJob(jobId)
                                                                                            setDashboardBuildProgress({
                                                                                                done: st.completed_widgets || 0,
                                                                                                total: st.total_widgets || DASHBOARD_MAX_WIDGETS,
                                                                                            })
                                                                                            if (st.dashboard_id) {
                                                                                                router.push(`/dashboard?id=${st.dashboard_id}&job_id=${jobId}`)
                                                                                                return
                                                                                            }
                                                                                            if (st.status === "failed" || st.status === "cancelled") {
                                                                                                throw new Error(st.error || "Dashboard build failed.")
                                                                                            }
                                                                                            await new Promise((r) => setTimeout(r, 1200))
                                                                                        }
                                                                                        throw new Error("Dashboard build timed out.")
                                                                                    }
                                                                                    await poll()
                                                                                } catch (e: unknown) {
                                                                                    setDashboardAiError(getErrorMessage(e) || "Failed to build the dashboard.")
                                                                                } finally {
                                                                                    setIsBuildingDashboard(false)
                                                                                    setDashboardBuildProgress(null)
                                                                                }
                                                                                return
                                                                            }
                                                                            await handleSendMessage(String(suggestion?.question || ""))
                                                                        }}
                                                                        className={cn(
                                                                            "group relative p-3 rounded-3xl",
                                                                            "bg-gradient-to-br from-slate-50 to-gray-50 dark:from-slate-800 dark:to-gray-900",
                                                                            "border border-slate-200/60 dark:border-slate-700/60",
                                                                            "shadow-sm hover:shadow-lg hover:shadow-slate-200/50 dark:hover:shadow-slate-900/50",
                                                                            "hover:scale-[1.02] active:scale-[0.98]",
                                                                            "hover:border-slate-300 dark:hover:border-slate-600",
                                                                            "transition-all duration-200 ease-out",
                                                                            "flex items-center justify-center",
                                                                            "min-h-[70px]",
                                                                            "overflow-hidden"
                                                                        )}
                                                                    >
                                                                        {/* Subtle gradient overlay on hover */}
                                                                        <div className="absolute inset-0 rounded-3xl bg-gradient-to-br from-blue-50/0 to-purple-50/0 group-hover:from-blue-50/30 group-hover:to-purple-50/20 dark:group-hover:from-blue-950/20 dark:group-hover:to-purple-950/10 transition-all duration-200" />

                                                                        {/* Content */}
                                                                        <p className="text-xs font-medium text-slate-700 dark:text-slate-200 text-center leading-relaxed px-2 break-words line-clamp-3 relative z-10">
                                                                            {isBuildingDashboard && kind === "action"
                                                                                ? (dashboardBuildProgress
                                                                                    ? `Creating dashboard (${dashboardBuildProgress.done}/${dashboardBuildProgress.total})...`
                                                                                    : "Creating dashboard...")
                                                                                : label}
                                                                        </p>
                                                                    </button>
                                                                </TooltipTrigger>
                                                                {/* Tooltip - show full text on hover */}
                                                                <TooltipContent side="top" className="text-xs max-w-[200px]">
                                                                    {label}
                                                                </TooltipContent>
                                                            </Tooltip>
                                                        )
                                                    })
                                                })()}
                                            </div>
                                            
                                            {/* Question text below cards - styled as AI message */}
                                            <div className="flex justify-start">
                                                <div className="relative max-w-[85%] rounded-2xl px-4 py-3 bg-muted/40 border border-border/50">
                                                    <p
                                                        role="status"
                                                        aria-live="polite"
                                                        className="text-sm text-foreground"
                                                    >
                                                        {isLoadingBootstrap
                                                            ? "Loading suggestions..."
                                                            : (chatBootstrap?.greeting)
                                                                ? chatBootstrap.greeting
                                                                : "How can I help you?"}
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    ) : (
                                        chatMessages.map((msg, index) => {
                                            // Check if this message is animating (messageId may have timestamp suffix)
                                            const isAnimating = flyingComet?.messageId?.startsWith(msg.id) ?? false
                                            
                                            return (
                                                <div key={msg.id} className="space-y-2">
                                                    <motion.div
                                                        ref={(el) => {
                                                            if (el) messageRefs.current[msg.id] = el
                                                        }}
                                                        animate={isAnimating ? {
                                                            scale: 0,
                                                            opacity: 0
                                                        } : {
                                                            scale: 1,
                                                            opacity: 1
                                                        }}
                                                        transition={{ duration: 0.3 }}
                                                        className={cn(
                                                            "flex",
                                                            msg.type === "user" ? "justify-end" : "justify-start"
                                                        )}
                                                    >
                                                        <div className={cn(
                                                            "relative max-w-[85%] rounded-2xl px-4 py-3",
                                                            msg.type === "user"
                                                                ? "bg-primary text-primary-foreground"
                                                                : "bg-muted/40 border border-border/50"
                                                        )}>
                                                            {/* Star icon for assistant messages */}
                                                            {msg.type === "assistant" && !isAnimating && (
                                                                <div className="absolute top-2 right-2 z-[50]">
                                                                    <Tooltip>
                                                                        <TooltipTrigger asChild>
                                                                            <button
                                                                                data-widget-menu
                                                                                onClick={(e) => {
                                                                                    e.stopPropagation()
                                                                                    setOpenWidgetMenu(openWidgetMenu === msg.id ? null : msg.id)
                                                                                }}
                                                                                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors group"
                                                                                aria-label="Visualize as widget"
                                                                            >
                                                                                <Star className="h-5 w-5 text-yellow-500 fill-yellow-500 group-hover:scale-110 transition-transform duration-200" />
                                                                            </button>
                                                                        </TooltipTrigger>
                                                                        <TooltipContent side="top" className="text-[10px] px-1.5 py-0.5 z-[60]">
                                                                            Create widget
                                                                        </TooltipContent>
                                                                    </Tooltip>
                                                                    
                                                                    {/* Widget Menu - Small lateral menu to the right */}
                                                                    <AnimatePresence>
                                                                        {openWidgetMenu === msg.id && (
                                                                            <motion.div 
                                                                                initial={{ opacity: 0, scale: 0.95, x: -10 }}
                                                                                animate={{ opacity: 1, scale: 1, x: 0 }}
                                                                                exit={{ opacity: 0, scale: 0.95, x: -10 }}
                                                                                transition={{ duration: 0.15 }}
                                                                                className="absolute top-0 left-full ml-1.5 bg-background/95 backdrop-blur-sm border border-border/50 rounded-md shadow-md z-[60] w-[110px]"
                                                                                data-widget-menu
                                                                            >
                                                                            <div className="py-0.5">
                                                                                <button
                                                                                    onClick={() => {
                                                                                        const messageElement = messageRefs.current[msg.id]
                                                                                        if (messageElement) {
                                                                                            handleCreateWidgetWithAnimation(
                                                                                                msg.id,
                                                                                                messageElement,
                                                                                                'kpi',
                                                                                                {
                                                                                                    title: 'AI Response',
                                                                                                    size: { width: 250, height: 120 },
                                                                                                    data: { 
                                                                                                        value: msg.content.substring(0, 50),
                                                                                                        change: '0%'
                                                                                                    }
                                                                                                }
                                                                                            )
                                                                                        }
                                                                                    }}
                                                                                    className="w-full flex items-center gap-1.5 px-2 py-1 hover:bg-accent/50 transition-colors text-[11px] text-left text-muted-foreground hover:text-foreground"
                                                                                >
                                                                                    <BarChart3 className="h-3 w-3 flex-shrink-0" />
                                                                                    <span className="truncate">KPI</span>
                                                                                </button>
                                                                                
                                                                                <div className="h-px bg-border/50 my-0.5 mx-1.5" />
                                                                                
                                                                                {[
                                                                                    { type: 'bar', label: 'Bar', icon: BarChart3 },
                                                                                    { type: 'pie', label: 'Pie', icon: PieChart },
                                                                                    { type: 'line', label: 'Line', icon: TrendingUp },
                                                                                    { type: 'scatter', label: 'Scatter', icon: Activity }
                                                                                ].map((chart) => {
                                                                                    const Icon = chart.icon
                                                                                    return (
                                                                                        <button
                                                                                            key={chart.type}
                                                                                            onClick={() => {
                                                                                                const messageElement = messageRefs.current[msg.id]
                                                                                                if (messageElement) {
                                                                                                    // Get real data from message if available
                                                                                                    const responseData = (msg as any).responseData
                                                                                                    let chartData: any = {
                                                                                                        type: chart.type,
                                                                                                        series: [0, 0, 0, 0, 0],
                                                                                                        labels: ['A', 'B', 'C', 'D', 'E'],
                                                                                                    }
                                                                                                    
                                                                                                    // Use real data if available
                                                                                                    if (responseData?.data_sample && Array.isArray(responseData.data_sample) && responseData.data_sample.length > 0) {
                                                                                                        const sample = responseData.data_sample
                                                                                                        const firstRow = sample[0]
                                                                                                        
                                                                                                        if (firstRow && typeof firstRow === 'object') {
                                                                                                            const keys = Object.keys(firstRow)
                                                                                                            
                                                                                                            // Find first string/categorical column for labels
                                                                                                            const labelKey = keys.find(k => {
                                                                                                                const val = firstRow[k]
                                                                                                                return typeof val === 'string' || (val != null && !isFinite(Number(val)))
                                                                                                            }) || keys[0]
                                                                                                            
                                                                                                            // Find first numeric column for values
                                                                                                            const valueKey = keys.find(k => {
                                                                                                                const val = firstRow[k]
                                                                                                                return typeof val === 'number' || (val != null && isFinite(Number(val)))
                                                                                                            }) || keys[1] || keys[0]
                                                                                                            
                                                                                                            if (labelKey && valueKey) {
                                                                                                                chartData.labels = sample.map((row: any) => String(row[labelKey] ?? ''))
                                                                                                                chartData.series = sample.map((row: any) => {
                                                                                                                    const val = row[valueKey]
                                                                                                                    return typeof val === 'number' ? val : (isFinite(Number(val)) ? Number(val) : 0)
                                                                                                                })
                                                                                                            }
                                                                                                        }
                                                                                                    }
                                                                                                    
                                                                                                    handleCreateWidgetWithAnimation(
                                                                                                        msg.id,
                                                                                                        messageElement,
                                                                                                        'chart',
                                                                                                        {
                                                                                                            title: `${chart.label} Chart`,
                                                                                                            size: { width: 320, height: 240 },
                                                                                                            data: chartData
                                                                                                        }
                                                                                                    )
                                                                                                }
                                                                                            }}
                                                                                            className="w-full flex items-center gap-1.5 px-2 py-1 hover:bg-accent/50 transition-colors text-[11px] text-left text-muted-foreground hover:text-foreground"
                                                                                        >
                                                                                            <Icon className="h-3 w-3 flex-shrink-0" />
                                                                                            <span className="truncate">{chart.label}</span>
                                                                                        </button>
                                                                                    )
                                                                                })}
                                                                                
                                                                                <div className="h-px bg-border/50 my-0.5 mx-1.5" />
                                                                                
                                                                                <button
                                                                                    onClick={() => {
                                                                                        const messageElement = messageRefs.current[msg.id]
                                                                                        if (messageElement) {
                                                                                            // Get real data from message if available
                                                                                            const responseData = (msg as any).responseData
                                                                                            let widgetData: any = {
                                                                                                title: 'AI Response Table',
                                                                                                size: { width: 400, height: 250 },
                                                                                                data: {
                                                                                                    columns: [],
                                                                                                    rows: []
                                                                                                }
                                                                                            }

                                                                                            // Use real data if available
                                                                                            if (responseData?.data_sample && responseData.data_sample.length > 0) {
                                                                                                const columns = Object.keys(responseData.data_sample[0])
                                                                                                const rows = responseData.data_sample.map((row: Record<string, any>) => 
                                                                                                    columns.map(col => row[col] ?? '')
                                                                                                )
                                                                                                widgetData.data = {
                                                                                                    columns,
                                                                                                    rows
                                                                                                }
                                                                                            } else {
                                                                                                // Fallback to empty table
                                                                                                widgetData.data = {
                                                                                                    columns: ['No data'],
                                                                                                    rows: [['No data available']]
                                                                                                }
                                                                                            }

                                                                                            handleCreateWidgetWithAnimation(
                                                                                                msg.id,
                                                                                                messageElement,
                                                                                                'table',
                                                                                                widgetData
                                                                                            )
                                                                                        }
                                                                                    }}
                                                                                    className="w-full flex items-center gap-1.5 px-2 py-1 hover:bg-accent/50 transition-colors text-[11px] text-left text-muted-foreground hover:text-foreground"
                                                                                >
                                                                                    <Table className="h-3 w-3 flex-shrink-0" />
                                                                                    <span className="truncate">Table</span>
                                                                                </button>
                                                                            </div>
                                                                            </motion.div>
                                                                        )}
                                                                    </AnimatePresence>
                                                                </div>
                                                            )}
                                                            {/* Show chosen datasets/tables if available */}
                                                            {msg.type === "assistant" && (
                                                                ((msg as any).responseData?.chosen_datasets && (msg as any).responseData.chosen_datasets.length > 0) ||
                                                                (msg as any).responseData?.chosen_table
                                                            ) && (
                                                                <div className="mb-3 pb-2 border-b border-border/30">
                                                                    <div className="flex items-center gap-2 mb-1.5">
                                                                        <Database className="h-3.5 w-3.5 text-muted-foreground" />
                                                                        <span className="text-[11px] text-muted-foreground font-semibold">Tables used by AI:</span>
                                                                    </div>
                                                                    <div className="flex flex-wrap gap-1.5">
                                                                        {((msg as any).responseData?.chosen_datasets && (msg as any).responseData.chosen_datasets.length > 0
                                                                            ? (msg as any).responseData.chosen_datasets
                                                                            : (msg as any).responseData?.chosen_table
                                                                                ? [(msg as any).responseData.chosen_table]
                                                                                : []
                                                                        ).map((table: string, idx: number) => (
                                                                            <Badge 
                                                                                key={idx}
                                                                                variant="secondary"
                                                                                className="text-[10px] px-2 py-1 h-auto font-medium bg-primary/10 text-primary border-primary/20"
                                                                            >
                                                                                <Table className="h-2.5 w-2.5 mr-1" />
                                                                                {table}
                                                                            </Badge>
                                                                        ))}
                                                                    </div>
                                                                </div>
                                                            )}
                                                            <p className="text-sm whitespace-pre-wrap leading-relaxed pr-8">
                                                                {msg.content}
                                                            </p>
                                                        </div>
                                                    </motion.div>
                                                    
                                                    {/* Action Icons - only show for assistant messages */}
                                                    {msg.type === "assistant" && (
                                                        <div className="flex items-center gap-1 px-1">
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            navigator.clipboard.writeText(msg.content)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Copy"
                                                                    >
                                                                        <Copy className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Copy
                                                                </TooltipContent>
                                                            </Tooltip>
                                                            
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            console.log("Good response:", msg.id)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Good response"
                                                                    >
                                                                        <ThumbsUp className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Good response
                                                                </TooltipContent>
                                                            </Tooltip>
                                                            
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            console.log("Bad response:", msg.id)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Bad response"
                                                                    >
                                                                        <ThumbsDown className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Bad response
                                                                </TooltipContent>
                                                            </Tooltip>
                                                            
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            console.log("Share:", msg.id)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Share"
                                                                    >
                                                                        <Share2 className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Share
                                                                </TooltipContent>
                                                            </Tooltip>
                                                            
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            console.log("Try again:", msg.id)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Try again"
                                                                    >
                                                                        <RefreshCw className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Try again
                                                                </TooltipContent>
                                                            </Tooltip>
                                                        </div>
                                                    )}
                                                </div>
                                            )
                                        })
                                    )}
                                    <div ref={chatEndRef} />
                                </div>
                            )}

                            {/* DATA TAB */}
                            {mainTab === "data" && (
                                <div className="px-4 py-3 space-y-4">
                                    {/* Show tables used by AI in recent responses */}
                                    {(() => {
                                        // If we are inspecting a specific widget, show its tables here (first card).
                                        if (currentWidgetId && usedTablesForWidget.length > 0) {
                                            const aiUsedTables = usedTablesForWidget
                                            return (
                                                <div className="mb-4 space-y-3">
                                                    <div className="flex items-center gap-2">
                                                        <Sparkles className="h-4 w-4 text-primary" />
                                                        <Label className="text-sm font-semibold text-primary">
                                                            Tables used by AI
                                                        </Label>
                                                        <Badge variant="secondary" className="text-[10px] px-2 py-0.5 ml-auto">
                                                            {aiUsedTables.length}
                                                        </Badge>
                                                    </div>
                                                    <p className="text-xs text-muted-foreground">
                                                        Tables used to generate this widget response:
                                                    </p>
                                                    <div className="flex flex-wrap gap-1.5">
                                                        {aiUsedTables.map((t: string) => (
                                                            <Badge key={t} variant="outline" className="text-[10px]">
                                                                {t}
                                                            </Badge>
                                                        ))}
                                                    </div>
                                                </div>
                                            )
                                        }

                                        // If a widget is selected but we don't have table info yet, show the empty state
                                        // for this widget (instead of aggregating from the whole chat).
                                        if (currentWidgetId && usedTablesForWidget.length === 0) {
                                            return (
                                                <div className="mb-4 p-4 bg-muted/30 border border-border rounded-lg text-center">
                                                    <Database className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
                                                    <p className="text-sm text-muted-foreground">
                                                        No tables have been used yet.
                                                    </p>
                                                    <p className="text-xs text-muted-foreground mt-1">
                                                        Ask a question to see which tables the AI picks to answer.
                                                    </p>
                                                </div>
                                            )
                                        }

                                        // Get all tables used by AI from all assistant messages
                                        const aiUsedTables = Array.from(new Set(
                                            chatMessages
                                                .filter(msg => msg.type === "assistant")
                                                .flatMap(msg => {
                                                    const responseData = (msg as any).responseData;
                                                    const datasets = responseData?.chosen_datasets || [];
                                                    const table = responseData?.chosen_table;
                                                    
                                                    // Debug log
                                                    if (msg.type === "assistant") {
                                                        console.log("Message responseData:", {
                                                            id: msg.id,
                                                            hasResponseData: !!responseData,
                                                            chosen_datasets: datasets,
                                                            chosen_table: table,
                                                            allKeys: responseData ? Object.keys(responseData) : []
                                                        })
                                                    }
                                                    
                                                    // Return datasets if available, otherwise fallback to table
                                                    if (datasets && datasets.length > 0) {
                                                        return datasets.filter((d: string) => d); // Filter out empty strings
                                                    }
                                                    if (table) {
                                                        return [table];
                                                    }
                                                    return [];
                                                })
                                        ))
                                        
                                        console.log("AI Used Tables:", aiUsedTables)
                                        
                                        if (aiUsedTables.length === 0) {
                                            return (
                                                <div className="mb-4 p-4 bg-muted/30 border border-border rounded-lg text-center">
                                                    <Database className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
                                                    <p className="text-sm text-muted-foreground">
                                                        No tables have been used yet.
                                                    </p>
                                                    <p className="text-xs text-muted-foreground mt-1">
                                                        Ask a question to see which tables the AI picks to answer.
                                                    </p>
                                                </div>
                                            )
                                        }
                                        
                                        return (
                                            <div className="mb-4 space-y-3">
                                                <div className="flex items-center gap-2">
                                                    <Sparkles className="h-4 w-4 text-primary" />
                                                    <Label className="text-sm font-semibold text-primary">Tables used by AI</Label>
                                                </div>
                                                <p className="text-xs text-muted-foreground">
                                                    Tables the AI picked to answer your questions:
                                                </p>
                                                <div className="border rounded-lg divide-y divide-border overflow-hidden">
                                                    {aiUsedTables.map((tableName: string, idx: number) => {
                                                        // Try to find table details from connectionTables
                                                        const tableDetails = connectionTables.find(t => 
                                                            t.name === tableName || t.fullName === tableName
                                                        )
                                                        
                                                        return (
                                                            <div 
                                                                key={idx}
                                                                className="px-3 py-2.5 flex items-center justify-between text-xs hover:bg-muted/30 transition-colors"
                                                            >
                                                                <div className="flex flex-col flex-1 min-w-0">
                                                                    <div className="flex items-center gap-1.5">
                                                                        <Table className="h-3.5 w-3.5 text-primary" />
                                                                        <span className="font-semibold">{tableName}</span>
                                                                        {tableDetails?.type === 'view' && (
                                                                            <Badge variant="outline" className="text-[9px] px-1 py-0 h-4">
                                                                                View
                                                                            </Badge>
                                                                        )}
                                                                    </div>
                                                                    {tableDetails && (
                                                                        <div className="flex items-center gap-2 mt-1">
                                                                            <span className="text-xs text-muted-foreground">
                                                                                {tableDetails.fullName} ({tableDetails.type === 'view' ? 'View' : 'Table'})
                                                                            </span>
                                                                            <Badge variant="secondary" className="text-[9px] px-1.5 py-0 h-4">
                                                                                {tableDetails.connectionName}
                                                                            </Badge>
                                                                        </div>
                                                                    )}
                                                                </div>
                                                                <Tooltip>
                                                                    <TooltipTrigger asChild>
                                                                        <button
                                                                            onClick={() => {
                                                                                // Add to knowledge if not already there
                                                                                if (!configureData.knowledge.includes(tableName)) {
                                                                                    setConfigureData(prev => ({
                                                                                        ...prev,
                                                                                        knowledge: [...prev.knowledge, tableName]
                                                                                    }))
                                                                                }
                                                                            }}
                                                                            className="p-1.5 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
                                                                            aria-label="Add to knowledge"
                                                                        >
                                                                            <Database className="w-4 h-4" />
                                                                        </button>
                                                                    </TooltipTrigger>
                                                                    <TooltipContent side="left" className="text-xs">
                                                                        Add to knowledge
                                                                    </TooltipContent>
                                                                </Tooltip>
                                                            </div>
                                                        )
                                                    })}
                                                </div>
                                            </div>
                                        )
                                    })()}

                                    {/* Second item: datasets (columns/fields) */}
                                    <div className="mb-4 space-y-3">
                                        <div className="flex items-center gap-2">
                                            <Database className="h-4 w-4 text-primary" />
                                            <Label className="text-sm font-semibold text-primary">Datasets</Label>
                                            {currentWidgetId ? (
                                                <Badge variant="secondary" className="text-[10px] px-2 py-0.5 ml-auto">
                                                    {usedColumnsForWidget.length}
                                                </Badge>
                                            ) : null}
                                        </div>
                                        <p className="text-xs text-muted-foreground">
                                            {currentWidgetId
                                                ? "Columns/fields returned for this widget:"
                                                : "Select a widget to see its columns/fields."}
                                        </p>
                                        {currentWidgetId ? (
                                            usedColumnsForWidget.length > 0 ? (
                                                <div className="flex flex-wrap gap-1.5">
                                                    {usedColumnsForWidget.map((c) => (
                                                        <Badge key={c} variant="outline" className="text-[10px]">
                                                            {c}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            ) : (
                                                <div className="p-3 bg-muted/20 border border-border rounded-lg text-center">
                                                    <p className="text-xs text-muted-foreground">
                                                        No columns/fields were returned yet.
                                                    </p>
                                                </div>
                                            )
                                        ) : null}
                                    </div>
                                    {/* Knowledge section */}
                                    <div className="space-y-3">
                                        {/* Tables used moved to the top of the Data tab */}

                                        <div className="flex items-center justify-between">
                                            <Label className="text-sm font-semibold">Knowledge (manually selected)</Label>
                                            <DropdownMenu>
                                                <DropdownMenuTrigger asChild>
                                                    <Button 
                                                        variant="outline" 
                                                        size="sm" 
                                                        className="h-7 px-2.5 rounded-lg text-xs font-medium shadow-sm hover:shadow transition-all duration-200 hover:bg-accent/50 border-border/60"
                                                        disabled={!!uploadingFile}
                                                    >
                                                        {uploadingFile ? (
                                                            <>
                                                                <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />
                                                                Uploading...
                                                            </>
                                                        ) : (
                                                            <>+ Add Dataset</>
                                                        )}
                                                    </Button>
                                                </DropdownMenuTrigger>
                                                <DropdownMenuContent align="end" className="w-48">
                                                    <DropdownMenuItem
                                                        onClick={() => csvInputRef.current?.click()}
                                                        disabled={!!uploadingFile}
                                                        className="cursor-pointer"
                                                    >
                                                        <FileText className="w-4 h-4 mr-2" />
                                                        <span>Upload CSV</span>
                                                    </DropdownMenuItem>
                                                    <DropdownMenuItem
                                                        onClick={() => excelInputRef.current?.click()}
                                                        disabled={!!uploadingFile}
                                                        className="cursor-pointer"
                                                    >
                                                        <Table className="w-4 h-4 mr-2" />
                                                        <span>Upload Excel</span>
                                                    </DropdownMenuItem>
                                                    <DropdownMenuItem
                                                        onClick={() => jsonInputRef.current?.click()}
                                                        disabled={!!uploadingFile}
                                                        className="cursor-pointer"
                                                    >
                                                        <FileJson className="w-4 h-4 mr-2" />
                                                        <span>Upload JSON</span>
                                                    </DropdownMenuItem>
                                                </DropdownMenuContent>
                                            </DropdownMenu>
                                        </div>
                                        <p className="text-xs text-muted-foreground">
                                            Files and datasets manually selected for this query.
                                        </p>
                                        <div className="border rounded-lg divide-y divide-border overflow-hidden">
                                            {/* Show manually selected items from knowledge */}
                                            {configureData.knowledge.length === 0 ? (
                                                <div className="px-3 py-4 text-xs text-muted-foreground text-center">
                                                    No datasets selected. AI will choose the necessary tables automatically.
                                                </div>
                                            ) : (
                                                <>
                                                    {configureData.knowledge
                                                        .filter(item => !removedItems.has(item))
                                                        .map((item) => {
                                                            // Check if it's a file
                                                            const isFile = uploadedFiles.some(f => f.id === item || f.name === item)
                                                            const fileInfo = uploadedFiles.find(f => f.id === item || f.name === item)
                                                            
                                                            // Check if it's a table from connections
                                                            const tableInfo = connectionTables.find(t => t.name === item || t.fullName === item)
                                                            
                                                            return (
                                                                <div 
                                                                    key={item}
                                                                    className="px-3 py-2 flex items-center justify-between text-xs hover:bg-muted/30 transition-colors"
                                                                >
                                                                    <div className="flex flex-col flex-1 min-w-0">
                                                                        <div className="flex items-center gap-1.5">
                                                                            {isFile ? (
                                                                                <>
                                                                                    {fileInfo?.type === 'csv' && <FileText className="h-3 w-3 text-muted-foreground" />}
                                                                                    {fileInfo?.type === 'excel' && <Table className="h-3 w-3 text-muted-foreground" />}
                                                                                    {fileInfo?.type === 'json' && <FileJson className="h-3 w-3 text-muted-foreground" />}
                                                                                </>
                                                                            ) : (
                                                                                <Table className="h-3 w-3 text-muted-foreground" />
                                                                            )}
                                                                            <span className="font-medium">{item}</span>
                                                                        </div>
                                                                        <div className="flex items-center gap-2 mt-0.5">
                                                                            <span className="text-xs text-muted-foreground">
                                                                                {isFile 
                                                                                    ? `${fileInfo?.type.toUpperCase()} File`
                                                                                    : tableInfo 
                                                                                        ? `${tableInfo.fullName} (${tableInfo.type === 'view' ? 'View' : 'Table'})`
                                                                                        : 'Dataset'
                                                                                }
                                                                            </span>
                                                                            {tableInfo && (
                                                                                <Badge variant="secondary" className="text-[9px] px-1.5 py-0 h-4">
                                                                                    {tableInfo.connectionName}
                                                                                </Badge>
                                                                            )}
                                                                        </div>
                                                                    </div>
                                                                    <Tooltip>
                                                                        <TooltipTrigger asChild>
                                                                            <button
                                                                                onClick={() => {
                                                                                    setConfigureData(prev => ({
                                                                                        ...prev,
                                                                                        knowledge: prev.knowledge.filter(k => k !== item)
                                                                                    }))
                                                                                    setRemovedItems(prev => new Set(prev).add(item))
                                                                                }}
                                                                                className="p-1.5 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                                                                                aria-label="Remove dataset"
                                                                            >
                                                                                <Trash2 className="w-4 h-4" />
                                                                            </button>
                                                                        </TooltipTrigger>
                                                                        <TooltipContent side="left" className="text-xs">
                                                                            Remove dataset
                                                                        </TooltipContent>
                                                                    </Tooltip>
                                                                </div>
                                                            )
                                                        })}
                                                </>
                                            )}
                                        </div>
                                        {/* Hidden file inputs */}
                                        <input
                                            ref={csvInputRef}
                                            type="file"
                                            accept=".csv"
                                            onChange={handleCSVUpload}
                                            className="hidden"
                                        />
                                        <input
                                            ref={excelInputRef}
                                            type="file"
                                            accept=".xlsx,.xls"
                                            onChange={handleExcelUpload}
                                            className="hidden"
                                        />
                                        <input
                                            ref={jsonInputRef}
                                            type="file"
                                            accept=".json"
                                            onChange={handleJSONUpload}
                                            className="hidden"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="sqlInstructions" className="text-sm font-semibold">
                                            Instructions
                                        </Label>
                                        <Textarea
                                            id="sqlInstructions"
                                            value={configureData.sqlInstructions}
                                            onChange={(e) =>
                                                setConfigureData({ ...configureData, sqlInstructions: e.target.value })
                                            }
                                            placeholder="Add specific instructions or constraints..."
                                            className="min-h-[80px] font-mono text-xs rounded-lg"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="finalSQL" className="text-sm font-semibold">
                                            SQL Query
                                        </Label>
                                        <Textarea
                                            id="finalSQL"
                                            value={finalSQL}
                                            onChange={(e) => setFinalSQL(e.target.value)}
                                            placeholder="SQL will be generated here..."
                                            className="min-h-[100px] font-mono text-xs rounded-lg bg-muted/30"
                                        />
                                    </div>
                                </div>
                            )}

                            {/* CONFIGURE TAB */}
                            {mainTab === "configure" && (
                                <div className="px-4 py-3 space-y-4">
                                    <div className="space-y-2">
                                        <Label htmlFor="question" className="text-sm font-medium">
                                            Question
                                        </Label>
                                        <Input
                                            id="question"
                                            value={configureData.question}
                                            onChange={(e) =>
                                                setConfigureData({ ...configureData, question: e.target.value })
                                            }
                                            placeholder="What is the revenue for this month?"
                                            className="rounded-lg text-sm"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="description" className="text-sm font-medium">
                                            Description
                                        </Label>
                                        <Textarea
                                            id="description"
                                            value={configureData.description}
                                            onChange={(e) =>
                                                setConfigureData({ ...configureData, description: e.target.value })
                                            }
                                            placeholder="Add a description for this query..."
                                            className="min-h-[60px] rounded-lg text-sm"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="instructions" className="text-sm font-medium">
                                            Instructions
                                        </Label>
                                        <Textarea
                                            id="instructions"
                                            value={configureData.instructions}
                                            onChange={(e) =>
                                                setConfigureData({ ...configureData, instructions: e.target.value })
                                            }
                                            placeholder="Add general instructions on how you want the AI to behave..."
                                            className="min-h-[100px] font-mono text-xs rounded-lg"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="responseFormat" className="text-sm font-medium">
                                            Response Format
                                        </Label>
                                        <Select
                                            value={configureData.responseFormat}
                                            onValueChange={(value) =>
                                                setConfigureData({ ...configureData, responseFormat: value })
                                            }
                                        >
                                            <SelectTrigger id="responseFormat" className="w-full rounded-lg text-sm">
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="text">Text</SelectItem>
                                                <SelectItem value="markdown">Markdown</SelectItem>
                                                <SelectItem value="json">JSON</SelectItem>
                                                <SelectItem value="table">Table</SelectItem>
                                                <SelectItem value="chart">Chart</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-3">
                                        <div className="space-y-2">
                                            <div className="flex items-center justify-between">
                                                <Label className="text-sm font-medium">Creativity</Label>
                                                <span className="text-xs text-muted-foreground">{configureData.creativity}%</span>
                                            </div>
                                            <Slider
                                                value={[configureData.creativity]}
                                                onValueChange={(value) =>
                                                    setConfigureData({ ...configureData, creativity: value[0] })
                                                }
                                                min={0}
                                                max={100}
                                                step={1}
                                                className="w-full"
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <div className="flex items-center justify-between">
                                                <Label className="text-sm font-medium">Length</Label>
                                                <span className="text-xs text-muted-foreground">{configureData.length}%</span>
                                            </div>
                                            <Slider
                                                value={[configureData.length]}
                                                onValueChange={(value) =>
                                                    setConfigureData({ ...configureData, length: value[0] })
                                                }
                                                min={0}
                                                max={100}
                                                step={1}
                                                className="w-full"
                                            />
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* PIPELINE TAB */}
                            {mainTab === "pipeline" && (
                                <div className="px-4 py-3 space-y-3">
                                    <div className="space-y-2">
                                        <h3 className="text-sm font-semibold">Pipeline Execution</h3>
                                        <p className="text-xs text-muted-foreground">
                                            Visualize the step-by-step process of how your question was processed and answered.
                                        </p>
                                    </div>
                                    <div className="space-y-2">
                                        <div className="border rounded-lg p-3 bg-background">
                                            <div className="flex items-center gap-2 mb-2">
                                                <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center">
                                                    <span className="text-xs font-semibold text-primary">1</span>
                                                </div>
                                                <h4 className="font-semibold text-sm">Question</h4>
                                            </div>
                                            <p className="text-xs text-muted-foreground ml-8">
                                                {configureData.question || chatMessages[0]?.content || "No question provided"}
                                            </p>
                                        </div>
                                        <div className="border rounded-lg p-3 bg-background">
                                            <div className="flex items-center gap-2 mb-2">
                                                <div className="w-6 h-6 rounded-full bg-purple-500/20 flex items-center justify-center">
                                                    <Database className="w-3 h-3 text-purple-600 dark:text-purple-400" />
                                                </div>
                                                <h4 className="font-semibold text-sm">Datasets</h4>
                                            </div>
                                            <p className="text-xs text-muted-foreground ml-8">
                                                {currentWidgetId
                                                    ? (usedDatasetsFromSql.length > 0
                                                        ? usedDatasetsFromSql.join(", ")
                                                        : (usedTablesForWidget.length > 0 ? usedTablesForWidget.join(", ") : "—"))
                                                    : (configureData.knowledge.length > 0
                                                        ? configureData.knowledge.join(", ")
                                                        : "No datasets selected")}
                                            </p>
                                        </div>
                                        <div className="border rounded-lg p-3 bg-background">
                                            <div className="flex items-center gap-2 mb-2">
                                                <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center">
                                                    <FileCode className="w-3 h-3 text-blue-600 dark:text-blue-400" />
                                                </div>
                                                <h4 className="font-semibold text-sm">SQL</h4>
                                            </div>
                                            <Textarea
                                                value={
                                                    currentWidgetId && (widget as any)?.data?.sql
                                                        ? String((widget as any).data.sql)
                                                        : (finalSQL || "-- Not executed")
                                                }
                                                readOnly
                                                className="mt-1 min-h-[140px] font-mono text-[11px] rounded-lg bg-muted/30"
                                            />
                                        </div>
                                        <div className="border rounded-lg p-3 bg-background">
                                            <div className="flex items-center gap-2 mb-2">
                                                <div className="w-6 h-6 rounded-full bg-green-500/20 flex items-center justify-center">
                                                    <span className="text-xs font-semibold text-green-600 dark:text-green-400">✓</span>
                                                </div>
                                                <h4 className="font-semibold text-sm">Answer</h4>
                                            </div>
                                            <p className="text-xs text-muted-foreground ml-8">
                                                {chatMessages.length > 0 && chatMessages[chatMessages.length - 1]?.type === "assistant"
                                                    ? chatMessages[chatMessages.length - 1].content
                                                    : "Not executed"}
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Input area - sempre na parte inferior */}
                        <div className="px-4 py-3 border-t border-border/50 flex-shrink-0">
                            {/* AI processing indicator - above input, left aligned */}
                            <AnimatePresence mode="wait">
                                {isProcessingQuery && (
                                    <motion.div
                                        key={loadingMessages[loadingStepIndex]}
                                        initial={{ opacity: 0, y: 4 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        exit={{ opacity: 0, y: -4 }}
                                        transition={{ duration: 0.25 }}
                                        className="mb-2 flex items-center gap-2 text-xs text-muted-foreground"
                                    >
                                        <Loader2 className="w-4 h-4 animate-spin text-primary" />
                                        <span>
                                            {loadingMessages[loadingStepIndex]}
                                        </span>
                                    </motion.div>
                                )}
                            </AnimatePresence>
                            
                            <form
                                onSubmit={handleSubmitQuestion}
                                className="flex items-center gap-2"
                            >
                                <div className="flex-1 relative">
                                    <input
                                        ref={expandedInputRef}
                                        type="text"
                                        placeholder="Ask anything..."
                                        value={question}
                                        onChange={(e) => setQuestion(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter' && !e.shiftKey) {
                                                e.preventDefault()
                                                handleSubmitQuestion(e as any)
                                            }
                                        }}
                                        className="w-full px-4 py-2.5 bg-muted/50 border border-border rounded-xl text-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/20 transition-all"
                                    />
                                </div>
                                <button 
                                    type="button"
                                    className="text-muted-foreground hover:text-foreground transition-colors p-2 rounded-full hover:bg-accent"
                                    aria-label="Voice input"
                                >
                                    <Mic className="h-4 w-4" />
                                </button>
                                <button 
                                    type="submit" 
                                    disabled={!question.trim() || isProcessingQuery}
                                    className={cn(
                                        "p-2 rounded-full transition-colors",
                                        question.trim() && !isProcessingQuery
                                            ? "bg-primary text-primary-foreground hover:bg-primary/90"
                                            : "bg-muted text-muted-foreground cursor-not-allowed"
                                    )}
                                    aria-label="Submit question"
                                >
                                    <Send className="h-4 w-4" />
                                </button>
                            </form>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>

        {/* Delete Confirmation Dialog */}
        <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
            <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                    <DialogTitle>Remove Dataset</DialogTitle>
                    <DialogDescription>
                        Are you sure you want to remove <strong>{itemToDelete?.name}</strong> from the datasets list?
                        {itemToDelete?.type === 'file' && ' This will also remove it from your uploaded files.'}
                    </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => {
                            setDeleteDialogOpen(false)
                            setItemToDelete(null)
                        }}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive"
                        onClick={handleConfirmDelete}
                    >
                        Remove
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
        </>
    )
}

