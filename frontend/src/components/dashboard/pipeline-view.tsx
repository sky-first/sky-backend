"use client"

import { useState } from "react"
import { motion } from "framer-motion"
import {
  Brain,
  Grid3x3,
  Users,
  Code,
  Table,
  CheckCircle2,
} from "lucide-react"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { usePipelineStore, type PipelineStep } from "@/store/pipeline-store"
import { cn } from "@/lib/utils"

const STEP_ICONS: Record<string, any> = {
  question: Brain,
  orchestrator: Grid3x3,
  project: Users,
  sql: Code,
  tables: Table,
  answer: CheckCircle2,
}

const STATUS_COLORS: Record<
  string,
  { border: string; text: string; badge: string }
> = {
  COMPLETED: {
    border: "border-emerald-500",
    text: "text-emerald-500",
    badge: "bg-emerald-500/10 text-emerald-500",
  },
  PROCESSING: {
    border: "border-sky-500",
    text: "text-sky-500",
    badge: "bg-sky-500/10 text-sky-500",
  },
  PENDING: {
    border: "border-muted",
    text: "text-muted-foreground",
    badge: "bg-muted text-muted-foreground",
  },
}

export function PipelineView() {
  const { steps, setStepContent } = usePipelineStore()
  const [selectedId, setSelectedId] = useState<string | null>(
    steps[0]?.id ?? null
  )
  const selectedStep = steps.find((s) => s.id === selectedId) ?? steps[0]
  const [draft, setDraft] = useState(selectedStep?.content ?? "")

  const handleSelect = (step: PipelineStep) => {
    setSelectedId(step.id)
    setDraft(step.content)
  }

  const handleReset = () => {
    setDraft(selectedStep?.content ?? "")
  }

  const handleSave = () => {
    if (!selectedStep) return
    setStepContent(selectedStep.id, draft)
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-full bg-primary/10 flex items-center justify-center text-primary">
            <Brain className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-base font-semibold">Pipeline View</h2>
            <p className="text-xs text-muted-foreground">
              Trace and edit the AI decision process
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Steps */}
        <div className="border-b border-border bg-muted/40 px-6 py-5">
          <div className="flex items-center gap-4 overflow-x-auto pb-2">
            {steps.map((step, index) => {
              const Icon = STEP_ICONS[step.kind] ?? Brain
              const colors = STATUS_COLORS[step.status] ?? STATUS_COLORS.PENDING
              const isSelected = selectedStep?.id === step.id

              return (
                <div key={step.id} className="flex items-center">
                  <button
                    type="button"
                    onClick={() => handleSelect(step)}
                    className={cn(
                      "group relative flex flex-col items-center gap-2 focus:outline-none",
                      !isSelected && "opacity-80 hover:opacity-100"
                    )}
                  >
                    <div
                      className={cn(
                        "h-14 w-14 rounded-full border-2 bg-card shadow-sm flex items-center justify-center transition-all duration-200",
                        colors.border,
                        isSelected && "ring-4 ring-primary/20 scale-105"
                      )}
                    >
                      <Icon className={cn("w-6 h-6", colors.text)} />
                    </div>
                    <div className="text-center w-28">
                      <p
                        className={cn(
                          "text-xs font-medium truncate",
                          isSelected ? "text-foreground" : "text-muted-foreground"
                        )}
                      >
                        {step.name}
                      </p>
                      <p
                        className={cn(
                          "mt-0.5 inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium",
                          colors.badge
                        )}
                      >
                        {step.status.toLowerCase()}
                      </p>
                    </div>
                  </button>
                  {index < steps.length - 1 && (
                    <div className="h-px w-10 bg-border mx-2" />
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Editor */}
        <div className="flex-1 flex flex-col px-6 py-4 gap-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex flex-col">
              <span className="text-xs font-medium text-muted-foreground">
                Editing step
              </span>
              <span className="text-sm font-semibold">
                {selectedStep?.name ?? "Select a step"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleReset}
                disabled={!selectedStep}
              >
                Reset
              </Button>
              <Button size="sm" onClick={handleSave} disabled={!selectedStep}>
                Save
              </Button>
            </div>
          </div>

          <div className="flex-1">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="w-full h-full min-h-[160px] resize-none text-xs font-mono"
              spellCheck={false}
              placeholder="Edit the content for this step..."
            />
          </div>
        </div>
      </div>
    </div>
  )
}


