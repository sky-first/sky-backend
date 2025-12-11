"use client"

import { useEffect, useState, useRef } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { X, Send, Plus, Mic, ThumbsUp, ThumbsDown, RefreshCw, Share2, Copy, MoreVertical, Database, FileCode, MessageSquare, CheckCircle2, ArrowRight, AlertCircle, FileText, Clock, Info } from "lucide-react"
import { usePipelineStore } from "@/store/pipeline-store"
import { useWidgetStore } from "@/store/widget-store"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Slider } from "@/components/ui/slider"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

type MainTab = "chat" | "data" | "configure" | "pipeline"

export function PipelineOverlay() {
  const {
    isOpen,
    close,
    currentWidgetId,
    chatMessages,
    aiResponses,
    configureData,
    addChatMessage,
    addAIResponse,
    updateConfigureData,
  } = usePipelineStore()
  const { widgets, updateWidget } = useWidgetStore()

  const [mainTab, setMainTab] = useState<MainTab>("chat")
  const [chatInput, setChatInput] = useState("")
  const [finalSQL, setFinalSQL] = useState("")
  const [pipelineErrors, setPipelineErrors] = useState<Record<string, { hasError: boolean; logs?: string }>>({
    question: { hasError: false },
    database: { hasError: false },
    sql: { hasError: false },
    answer: { hasError: false },
  })
  const [selectedErrorStep, setSelectedErrorStep] = useState<string | null>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const chatContainerRef = useRef<HTMLDivElement>(null)

  const widget = widgets.find((w) => w.id === currentWidgetId)

  // Helper: Detect if pipeline has been executed
  const hasPipelineExecuted = () => {
    const hasQuestion = !!(configureData.question || chatMessages[0]?.content)
    const hasDatabase = configureData.knowledge.length > 0
    const hasSQL = !!(finalSQL && 
      finalSQL !== "-- Select datasets to generate SQL" && 
      finalSQL !== "-- No SQL generated yet" &&
      finalSQL !== "-- Not executed")
    const hasAnswer = !!(aiResponses[aiResponses.length - 1]?.content || widget?.data?.answer)
    
    // Pipeline is considered executed if at least database or SQL or answer exists
    return hasDatabase || hasSQL || hasAnswer
  }

  const pipelineExecuted = hasPipelineExecuted()

  // Helper: Get step status
  const getStepStatus = (stepName: 'question' | 'database' | 'sql' | 'answer') => {
    const stepError = pipelineErrors[stepName]
    if (stepError.hasError) return 'error'
    
    switch (stepName) {
      case 'question':
        return !!(configureData.question || chatMessages[0]?.content) ? 'completed' : 'not-executed'
      case 'database':
        return configureData.knowledge.length > 0 ? 'completed' : 'not-executed'
      case 'sql':
        return !!(finalSQL && 
          finalSQL !== "-- Select datasets to generate SQL" && 
          finalSQL !== "-- No SQL generated yet" &&
          finalSQL !== "-- Not executed") ? 'completed' : 'not-executed'
      case 'answer':
        return !!(aiResponses[aiResponses.length - 1]?.content || widget?.data?.answer) ? 'completed' : 'not-executed'
      default:
        return 'not-executed'
    }
  }

  // Auto-scroll chat to bottom
  useEffect(() => {
    if (mainTab === "chat" && chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [chatMessages, aiResponses, mainTab])

  // Prevenir scroll do body quando o modal está aberto
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = ""
    }
    return () => {
      document.body.style.overflow = ""
    }
  }, [isOpen])

  // Fechar com ESC
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") close()
    }
    if (isOpen) {
      document.addEventListener("keydown", handler)
    }
    return () => document.removeEventListener("keydown", handler)
  }, [isOpen, close])

  // Gerar SQL final baseado nos datasets selecionados
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

  const handleSendMessage = () => {
    if (!chatInput.trim()) return

    addChatMessage(chatInput)
    // Simular resposta da IA
    setTimeout(() => {
      const mockResponse = `This is a generated response for: "${chatInput}"

Here is a detailed analysis with relevant insights and recommendations based on the available data.`
      addAIResponse(mockResponse)
    }, 1000)

    setChatInput("")
  }

  // Salvar automaticamente quando houver mudanças
  useEffect(() => {
    if (!widget || !isOpen) return

    // Sempre usar a última resposta
    const lastResponse = aiResponses[aiResponses.length - 1]
    if (lastResponse) {
      updateWidget(widget.id, {
        data: {
          ...widget.data,
          answer: lastResponse.content,
          question: configureData.question || widget.data?.question,
        },
      })
    }
  }, [aiResponses.length, configureData.question, widget?.id, isOpen])

  if (!isOpen) return null

  return (
    <AnimatePresence>
      <>
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 bg-black/20 backdrop-blur-[1px] z-[80] pointer-events-auto"
          onClick={close}
        />

        {/* Modal flutuante */}
        <motion.div
          initial={{ x: "100%", opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: "100%", opacity: 0 }}
          transition={{ type: "spring", stiffness: 260, damping: 26 }}
          className="fixed right-8 top-8 bottom-8 w-full max-w-2xl bg-background border border-border rounded-2xl shadow-2xl z-[81] pointer-events-auto flex flex-col overflow-hidden"
        >
          {/* Top nav (Chat | Data | Configure) - Centralizado */}
          <div className="px-6 pt-6 pb-4 border-b border-border/50 flex items-center justify-center gap-3 flex-shrink-0 relative">
            <div className="flex items-center gap-2">
              {([
                { id: "chat", label: "Chat" },
                { id: "data", label: "Data" },
                { id: "configure", label: "Configure" },
                { id: "pipeline", label: "Pipeline" },
              ] as const).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setMainTab(item.id)}
                  className={cn(
                    "px-6 py-3 rounded-lg text-sm font-bold transition-all duration-200",
                    mainTab === item.id
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 absolute right-4"
              onClick={close}
            >
              <X className="w-4 h-4" />
            </Button>
          </div>

          {/* Main content - com scroll próprio */}
          <div className="flex-1 flex flex-col overflow-hidden min-h-0">
            {/* CHAT TAB */}
            {mainTab === "chat" && (
              <div className="flex-1 flex flex-col h-full overflow-hidden">
                {/* Chat area - com scroll próprio */}
                <div
                  ref={chatContainerRef}
                  className="flex-1 overflow-y-auto px-6 py-6 custom-scrollbar"
                  style={{ scrollBehavior: "smooth" }}
                >
                  <div className="max-w-3xl mx-auto space-y-6">
                    {/* Mensagem inicial do sistema (se não houver mensagens) */}
                    {chatMessages.length === 0 && (
                      <div className="space-y-3 text-center py-8">
                        <div className="text-foreground text-base leading-relaxed">
                          <p className="mb-2">
                            Hi! I'll help you build a new AI assistant. You can say something like,
                          </p>
                          <p className="text-muted-foreground italic">
                            "make a creative who helps generate visuals for new products"
                          </p>
                          <p className="text-muted-foreground italic mt-1">
                            or "make a software engineer who helps format my code."
                          </p>
                        </div>
                        <p className="text-foreground font-medium">What would you like to make?</p>
                      </div>
                    )}

                    {/* Mensagens do chat - estilo Gemini */}
                    {chatMessages.map((msg, msgIndex) => {
                      // Encontrar respostas relacionadas a esta mensagem
                      const relatedResponses = aiResponses.filter((_, respIndex) => {
                        return respIndex === msgIndex
                      })

                      return (
                        <div key={msg.id} className="space-y-4">
                          {/* Mensagem do usuário - estilo Gemini (bubble simples) */}
                          <div className="flex justify-end">
                            <div className="max-w-[85%] sm:max-w-[75%]">
                              <div className="bg-muted/40 border border-border/50 rounded-2xl px-4 py-3">
                                <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                                  {msg.content}
                                </p>
                              </div>
                            </div>
                          </div>

                          {/* Respostas da IA - estilo Gemini (sem bubble, texto direto) */}
                          {relatedResponses.length > 0 && (
                            <div className="space-y-3">
                              {relatedResponses.map((response, respIdx) => {
                                const isLast = respIdx === relatedResponses.length - 1
                                return (
                                  <div key={response.id} className="flex justify-start">
                                    <div className="max-w-[85%] sm:max-w-[75%] w-full">
                                      <div className="space-y-2">
                                        {/* Texto da resposta - estilo Gemini (sem bubble, sem borda) */}
                                        <div>
                                          <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                                            {response.content}
                                          </p>
                                        </div>

                                        {/* Botões de interação - estilo Gemini (apenas na última resposta) */}
                                        {isLast && (
                                          <div className="flex items-center gap-1 pt-1">
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                            >
                                              <ThumbsUp className="w-4 h-4" />
                                            </Button>
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                            >
                                              <ThumbsDown className="w-4 h-4" />
                                            </Button>
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                            >
                                              <RefreshCw className="w-4 h-4" />
                                            </Button>
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                            >
                                              <Share2 className="w-4 h-4" />
                                            </Button>
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                            >
                                              <Copy className="w-4 h-4" />
                                            </Button>
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                            >
                                              <MoreVertical className="w-4 h-4" />
                                            </Button>
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          )}

                          {/* Confirmação do sistema (após primeira resposta) */}
                          {msgIndex === 0 && relatedResponses.length > 0 && (
                            <div className="flex justify-start">
                              <div className="max-w-[85%] sm:max-w-[75%]">
                                <div className="text-sm text-muted-foreground italic">
                                  Great! I've loaded the initial behavior.
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      )
                    })}
                    <div ref={chatEndRef} />
                  </div>
                </div>

                {/* Chat input - estilo Gemini (alinhado) */}
                <div className="px-6 py-4 border-t border-border/50 bg-background flex-shrink-0">
                  <div className="max-w-3xl mx-auto">
                    <div className="relative flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9 rounded-full hover:bg-accent flex-shrink-0"
                      >
                        <Plus className="w-4 h-4 text-muted-foreground" />
                      </Button>
                      <div className="flex-1 relative">
                        <textarea
                          value={chatInput}
                          onChange={(e) => {
                            setChatInput(e.target.value)
                            // Auto-resize
                            e.target.style.height = "auto"
                            e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault()
                              handleSendMessage()
                            }
                          }}
                          placeholder="Ask anything..."
                          className={cn(
                            "w-full min-h-[52px] max-h-[200px] px-4 py-3.5 pr-24",
                            "bg-muted/50 border border-border rounded-2xl",
                            "text-sm text-foreground placeholder:text-muted-foreground",
                            "resize-none outline-none overflow-y-auto",
                            "focus:border-primary/50 focus:ring-2 focus:ring-primary/20",
                            "transition-all duration-200"
                          )}
                          rows={1}
                          style={{
                            scrollbarWidth: "thin",
                          }}
                        />
                        <div className="absolute right-2 bottom-2 flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 rounded-full hover:bg-accent"
                          >
                            <Mic className="w-4 h-4 text-muted-foreground" />
                          </Button>
                          <Button
                            onClick={handleSendMessage}
                            disabled={!chatInput.trim()}
                            size="icon"
                            className={cn(
                              "h-8 w-8 rounded-full transition-all",
                              chatInput.trim()
                                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                                : "bg-muted text-muted-foreground cursor-not-allowed"
                            )}
                          >
                            <Send className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* DATA TAB */}
            {mainTab === "data" && (
              <div className="flex-1 overflow-y-auto px-6 py-6 custom-scrollbar">
                <div className="max-w-2xl mx-auto space-y-6">
                  <div className="space-y-3">
                    <Label className="text-base font-semibold">Knowledge (Datasets)</Label>
                    <p className="text-sm text-muted-foreground">
                      Select tables, files, or data sources to use for this query.
                    </p>
                    <div className="border rounded-lg divide-y divide-border overflow-hidden">
                      <div className="px-4 py-3 flex items-center justify-between text-sm hover:bg-muted/30 transition-colors">
                        <div className="flex flex-col">
                          <span className="font-medium">revenue_ledger</span>
                          <span className="text-xs text-muted-foreground">
                            analytics.revenue_ledger (Table)
                          </span>
                        </div>
                        <input
                          type="checkbox"
                          checked={configureData.knowledge.includes("revenue_ledger")}
                          onChange={(e) => {
                            const knowledge = e.target.checked
                              ? [...configureData.knowledge, "revenue_ledger"]
                              : configureData.knowledge.filter((k) => k !== "revenue_ledger")
                            updateConfigureData({ knowledge })
                          }}
                          className="w-4 h-4 rounded cursor-pointer"
                        />
                      </div>
                      <div className="px-4 py-3 flex items-center justify-between text-sm hover:bg-muted/30 transition-colors">
                        <div className="flex flex-col">
                          <span className="font-medium">billing_invoice</span>
                          <span className="text-xs text-muted-foreground">
                            teambIue_finance.silver.billing_invoice
                          </span>
                        </div>
                        <input
                          type="checkbox"
                          checked={configureData.knowledge.includes("billing_invoice")}
                          onChange={(e) => {
                            const knowledge = e.target.checked
                              ? [...configureData.knowledge, "billing_invoice"]
                              : configureData.knowledge.filter((k) => k !== "billing_invoice")
                            updateConfigureData({ knowledge })
                          }}
                          className="w-4 h-4 rounded cursor-pointer"
                        />
                      </div>
                      <div className="px-4 py-3 flex items-center justify-between text-sm hover:bg-muted/30 transition-colors">
                        <div className="flex flex-col">
                          <span className="font-medium">customers_dim</span>
                          <span className="text-xs text-muted-foreground">
                            analytics.customers_dim (View)
                          </span>
                        </div>
                        <input
                          type="checkbox"
                          checked={configureData.knowledge.includes("customers_dim")}
                          onChange={(e) => {
                            const knowledge = e.target.checked
                              ? [...configureData.knowledge, "customers_dim"]
                              : configureData.knowledge.filter((k) => k !== "customers_dim")
                            updateConfigureData({ knowledge })
                          }}
                          className="w-4 h-4 rounded cursor-pointer"
                        />
                      </div>
                    </div>
                    <Button variant="outline" size="sm" className="w-full rounded-lg">
                      + Add Data Source
                    </Button>
                  </div>

                  <div className="space-y-3">
                    <Label htmlFor="sqlInstructions" className="text-base font-semibold">
                      Instructions
                    </Label>
                    <p className="text-sm text-muted-foreground">
                      Add specific instructions or constraints that will be used to generate the final query.
                    </p>
                    <Textarea
                      id="sqlInstructions"
                      value={configureData.sqlInstructions}
                      onChange={(e) =>
                        updateConfigureData({ sqlInstructions: e.target.value })
                      }
                      placeholder="Add specific instructions or constraints..."
                      className="min-h-[150px] font-mono text-xs rounded-lg"
                    />
                  </div>

                  <div className="space-y-3">
                    <Label htmlFor="finalSQL" className="text-base font-semibold">
                      SQL Query
                    </Label>
                    <p className="text-sm text-muted-foreground">
                      This SQL will be generated based on your selections. You can edit it directly if needed.
                    </p>
                    <Textarea
                      id="finalSQL"
                      value={finalSQL}
                      onChange={(e) => setFinalSQL(e.target.value)}
                      placeholder="SQL will be generated here..."
                      className="min-h-[200px] font-mono text-xs rounded-lg bg-muted/30"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* PIPELINE TAB */}
            {mainTab === "pipeline" && (
              <div className="flex-1 overflow-y-auto px-6 py-6 custom-scrollbar">
                <div className="max-w-3xl mx-auto space-y-6">
                  <div className="space-y-2">
                    <h3 className="text-lg font-semibold">Pipeline Execution</h3>
                    <p className="text-sm text-muted-foreground">
                      Visualize the step-by-step process of how your question was processed and answered.
                    </p>
                  </div>

                  {/* Informative Banner */}
                  {!pipelineExecuted && (
                    <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                      <div className="flex items-start gap-3">
                        <Info className="w-5 h-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                          <p className="text-sm font-medium text-blue-900 dark:text-blue-100 mb-1">
                            Pipeline Not Executed
                          </p>
                          <p className="text-xs text-blue-700 dark:text-blue-300">
                            This widget hasn't been processed through the pipeline yet. Configure it in the Configure tab to generate results.
                          </p>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Pipeline Flowchart - Vertical */}
                  <div className="space-y-4">
                    {/* Question Step */}
                    {(() => {
                      const stepError = pipelineErrors.question
                      const status = getStepStatus('question')
                      const hasError = status === 'error'
                      const isCompleted = status === 'completed'
                      const isNotExecuted = status === 'not-executed'
                      
                      return (
                        <div 
                          className={cn(
                            "border rounded-lg p-4 transition-all",
                            hasError 
                              ? "border-red-500 bg-red-50 dark:bg-red-900/10 hover:bg-red-100 dark:hover:bg-red-900/20 cursor-pointer" 
                              : isNotExecuted
                              ? "border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/30"
                              : "bg-background"
                          )}
                          onClick={() => hasError && setSelectedErrorStep("question")}
                        >
                          <div className="flex items-start gap-4">
                            <div className={cn(
                              "flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center",
                              hasError
                                ? "bg-red-100 dark:bg-red-900/30"
                                : isCompleted
                                ? "bg-blue-100 dark:bg-blue-900/30"
                                : "bg-gray-200 dark:bg-gray-800"
                            )}>
                              {hasError ? (
                                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                              ) : isCompleted ? (
                                <MessageSquare className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                              ) : (
                                <Clock className="w-5 h-5 text-gray-400 dark:text-gray-500" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-2">
                                <h4 className="font-semibold text-sm">Question</h4>
                                {hasError ? (
                                  <AlertCircle className="w-4 h-4 text-red-500" />
                                ) : isCompleted ? (
                                  <CheckCircle2 className="w-4 h-4 text-green-500" />
                                ) : (
                                  <span className="text-xs text-gray-400 dark:text-gray-500 font-normal">Not Executed</span>
                                )}
                              </div>
                              <p className={cn(
                                "text-sm",
                                isNotExecuted 
                                  ? "text-gray-400 dark:text-gray-500 italic" 
                                  : "text-muted-foreground"
                              )}>
                                {configureData.question || chatMessages[0]?.content || "No question provided"}
                              </p>
                            </div>
                          </div>
                        </div>
                      )
                    })()}

                    {/* Arrow */}
                    <div className="flex justify-center">
                      <ArrowRight className="w-5 h-5 text-muted-foreground rotate-90" />
                    </div>

                    {/* Database Step */}
                    {(() => {
                      const stepError = pipelineErrors.database
                      const status = getStepStatus('database')
                      const hasError = status === 'error'
                      const isCompleted = status === 'completed'
                      const isNotExecuted = status === 'not-executed'
                      
                      return (
                        <div 
                          className={cn(
                            "border rounded-lg p-4 transition-all",
                            hasError 
                              ? "border-red-500 bg-red-50 dark:bg-red-900/10 hover:bg-red-100 dark:hover:bg-red-900/20 cursor-pointer" 
                              : isNotExecuted
                              ? "border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/30"
                              : "bg-background"
                          )}
                          onClick={() => hasError && setSelectedErrorStep("database")}
                        >
                          <div className="flex items-start gap-4">
                            <div className={cn(
                              "flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center",
                              hasError
                                ? "bg-red-100 dark:bg-red-900/30"
                                : isCompleted
                                ? "bg-purple-100 dark:bg-purple-900/30"
                                : "bg-gray-200 dark:bg-gray-800"
                            )}>
                              {hasError ? (
                                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                              ) : isCompleted ? (
                                <Database className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                              ) : (
                                <Clock className="w-5 h-5 text-gray-400 dark:text-gray-500" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-2">
                                <h4 className="font-semibold text-sm">Database</h4>
                                {hasError ? (
                                  <AlertCircle className="w-4 h-4 text-red-500" />
                                ) : isCompleted ? (
                                  <CheckCircle2 className="w-4 h-4 text-green-500" />
                                ) : (
                                  <span className="text-xs text-gray-400 dark:text-gray-500 font-normal">Not Executed</span>
                                )}
                              </div>
                              <div className="space-y-2">
                                {configureData.knowledge.length > 0 ? (
                                  <div className="flex flex-wrap gap-2">
                                    {configureData.knowledge.map((db, idx) => (
                                      <span
                                        key={idx}
                                        className="px-2 py-1 text-xs bg-muted rounded-md text-foreground"
                                      >
                                        {db}
                                      </span>
                                    ))}
                                  </div>
                                ) : (
                                  <p className="text-sm text-gray-400 dark:text-gray-500 italic">
                                    Not executed
                                  </p>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      )
                    })()}

                    {/* Arrow */}
                    <div className="flex justify-center">
                      <ArrowRight className="w-5 h-5 text-muted-foreground rotate-90" />
                    </div>

                    {/* SQL Step */}
                    {(() => {
                      const stepError = pipelineErrors.sql
                      const status = getStepStatus('sql')
                      const hasError = status === 'error'
                      const isCompleted = status === 'completed'
                      const isNotExecuted = status === 'not-executed'
                      
                      return (
                        <div 
                          className={cn(
                            "border rounded-lg p-4 transition-all",
                            hasError 
                              ? "border-red-500 bg-red-50 dark:bg-red-900/10 hover:bg-red-100 dark:hover:bg-red-900/20 cursor-pointer" 
                              : isNotExecuted
                              ? "border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/30"
                              : "bg-background"
                          )}
                          onClick={() => hasError && setSelectedErrorStep("sql")}
                        >
                          <div className="flex items-start gap-4">
                            <div className={cn(
                              "flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center",
                              hasError
                                ? "bg-red-100 dark:bg-red-900/30"
                                : isCompleted
                                ? "bg-green-100 dark:bg-green-900/30"
                                : "bg-gray-200 dark:bg-gray-800"
                            )}>
                              {hasError ? (
                                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                              ) : isCompleted ? (
                                <FileCode className="w-5 h-5 text-green-600 dark:text-green-400" />
                              ) : (
                                <Clock className="w-5 h-5 text-gray-400 dark:text-gray-500" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-2">
                                <h4 className="font-semibold text-sm">SQL</h4>
                                {hasError ? (
                                  <AlertCircle className="w-4 h-4 text-red-500" />
                                ) : isCompleted ? (
                                  <CheckCircle2 className="w-4 h-4 text-green-500" />
                                ) : (
                                  <span className="text-xs text-gray-400 dark:text-gray-500 font-normal">Not Executed</span>
                                )}
                              </div>
                              <div className={cn(
                                "rounded-lg p-3 font-mono text-xs overflow-x-auto",
                                isNotExecuted
                                  ? "bg-gray-100 dark:bg-gray-800/50"
                                  : "bg-muted/50"
                              )}>
                                <pre className={cn(
                                  "whitespace-pre-wrap",
                                  isNotExecuted
                                    ? "text-gray-400 dark:text-gray-500"
                                    : "text-foreground"
                                )}>
                                  {finalSQL || configureData.sqlInstructions || "-- Not executed"}
                                </pre>
                              </div>
                            </div>
                          </div>
                        </div>
                      )
                    })()}

                    {/* Arrow */}
                    <div className="flex justify-center">
                      <ArrowRight className="w-5 h-5 text-muted-foreground rotate-90" />
                    </div>

                    {/* Answer Step */}
                    {(() => {
                      const stepError = pipelineErrors.answer
                      const status = getStepStatus('answer')
                      const hasError = status === 'error'
                      const isCompleted = status === 'completed'
                      const isNotExecuted = status === 'not-executed'
                      
                      return (
                        <div 
                          className={cn(
                            "border rounded-lg p-4 transition-all",
                            hasError 
                              ? "border-red-500 bg-red-50 dark:bg-red-900/10 hover:bg-red-100 dark:hover:bg-red-900/20 cursor-pointer" 
                              : isNotExecuted
                              ? "border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/30"
                              : "bg-background"
                          )}
                          onClick={() => hasError && setSelectedErrorStep("answer")}
                        >
                          <div className="flex items-start gap-4">
                            <div className={cn(
                              "flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center",
                              hasError
                                ? "bg-red-100 dark:bg-red-900/30"
                                : isCompleted
                                ? "bg-orange-100 dark:bg-orange-900/30"
                                : "bg-gray-200 dark:bg-gray-800"
                            )}>
                              {hasError ? (
                                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                              ) : isCompleted ? (
                                <CheckCircle2 className="w-5 h-5 text-orange-600 dark:text-orange-400" />
                              ) : (
                                <Clock className="w-5 h-5 text-gray-400 dark:text-gray-500" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-2">
                                <h4 className="font-semibold text-sm">Answer</h4>
                                {hasError ? (
                                  <AlertCircle className="w-4 h-4 text-red-500" />
                                ) : isCompleted ? (
                                  <CheckCircle2 className="w-4 h-4 text-green-500" />
                                ) : (
                                  <span className="text-xs text-gray-400 dark:text-gray-500 font-normal">Not Executed</span>
                                )}
                              </div>
                              <div className={cn(
                                "text-sm whitespace-pre-wrap",
                                isNotExecuted
                                  ? "text-gray-400 dark:text-gray-500 italic"
                                  : "text-foreground"
                              )}>
                                {aiResponses[aiResponses.length - 1]?.content || widget?.data?.answer || "Not executed"}
                              </div>
                            </div>
                          </div>
                        </div>
                      )
                    })()}
                  </div>

                  {/* Logs Modal */}
                  {selectedErrorStep && (
                    <AnimatePresence>
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 bg-black/20 backdrop-blur-[1px] z-[90] flex items-center justify-center p-4"
                        onClick={() => setSelectedErrorStep(null)}
                      >
                        <motion.div
                          initial={{ scale: 0.95, opacity: 0 }}
                          animate={{ scale: 1, opacity: 1 }}
                          exit={{ scale: 0.95, opacity: 0 }}
                          className="bg-background border border-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {/* Header */}
                          <div className="px-6 py-4 border-b border-border flex items-center justify-between">
                            <div className="flex items-center gap-3">
                              <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                                <FileText className="w-5 h-5 text-red-600 dark:text-red-400" />
                              </div>
                              <div>
                                <h3 className="font-semibold text-lg">Error Logs</h3>
                                <p className="text-sm text-muted-foreground">
                                  {selectedErrorStep.charAt(0).toUpperCase() + selectedErrorStep.slice(1)} Step
                                </p>
                              </div>
                            </div>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => setSelectedErrorStep(null)}
                              className="h-8 w-8"
                            >
                              <X className="w-4 h-4" />
                            </Button>
                          </div>

                          {/* Logs Content */}
                          <div className="flex-1 overflow-y-auto p-6">
                            <div className="bg-muted/50 rounded-lg p-4 font-mono text-xs">
                              <pre className="whitespace-pre-wrap text-foreground">
                                {pipelineErrors[selectedErrorStep]?.logs || "No logs available"}
                              </pre>
                            </div>
                          </div>
                        </motion.div>
                      </motion.div>
                    </AnimatePresence>
                  )}
                </div>
              </div>
            )}

            {/* CONFIGURE TAB */}
            {mainTab === "configure" && (
              <div className="flex-1 overflow-y-auto px-6 py-6 custom-scrollbar">
                <div className="max-w-2xl mx-auto space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="question" className="text-sm font-medium">
                      Question
                    </Label>
                    <Input
                      id="question"
                      value={configureData.question}
                      onChange={(e) =>
                        updateConfigureData({ question: e.target.value })
                      }
                      placeholder="What is the revenue for this month?"
                      className="rounded-lg"
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
                        updateConfigureData({ description: e.target.value })
                      }
                      placeholder="Add a description for this query..."
                      className="min-h-[100px] rounded-lg"
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
                        updateConfigureData({ instructions: e.target.value })
                      }
                      placeholder="Add general instructions on how you want the AI to behave..."
                      className="min-h-[200px] font-mono text-xs rounded-lg"
                    />
                    <p className="text-xs text-muted-foreground">
                      Examples: * MCA stands for My Company Abbreviation * Countries
                      are stored with two characters (e.g. US, IT)
                    </p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="responseFormat" className="text-sm font-medium">
                      Response Format
                    </Label>
                    <Select
                      value={configureData.responseFormat}
                      onValueChange={(value) =>
                        updateConfigureData({ responseFormat: value })
                      }
                    >
                      <SelectTrigger id="responseFormat" className="w-full rounded-lg">
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

                  <div className="space-y-6">
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <Label className="text-sm font-medium">Creativity</Label>
                        <span className="text-sm text-muted-foreground">
                          {configureData.creativity}%
                        </span>
                      </div>
                      <Slider
                        value={[configureData.creativity]}
                        onValueChange={([value]) =>
                          updateConfigureData({ creativity: value })
                        }
                        min={0}
                        max={100}
                        step={1}
                        className="w-full"
                      />
                      <div className="flex justify-between text-xs text-muted-foreground px-1">
                        <span>Less Creative</span>
                        <span>More Creative</span>
                      </div>
                    </div>

                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <Label className="text-sm font-medium">Length</Label>
                        <span className="text-sm text-muted-foreground">
                          {configureData.length}%
                        </span>
                      </div>
                      <Slider
                        value={[configureData.length]}
                        onValueChange={([value]) =>
                          updateConfigureData({ length: value })
                        }
                        min={0}
                        max={100}
                        step={1}
                        className="w-full"
                      />
                      <div className="flex justify-between text-xs text-muted-foreground px-1">
                        <span>Shorter</span>
                        <span>Longer</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

        </motion.div>
      </>
    </AnimatePresence>
  )
}
