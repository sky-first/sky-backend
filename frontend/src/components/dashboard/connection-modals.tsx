"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Link2, ChevronLeft, Info } from "lucide-react"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { ConnectorDefinition, CONNECTOR_REGISTRY } from "@/lib/connectors/connector-registry"
import { DataConnection } from "@/lib/types/connections"
import { DynamicFormField } from "./dynamic-form-field"

interface ConnectorSelectorModalProps {
  isOpen: boolean
  onClose: () => void
  onSelect: (connector: ConnectorDefinition) => void
  isDark: boolean
}

export function ConnectorSelectorModal({ isOpen, onClose, onSelect, isDark }: ConnectorSelectorModalProps) {
  if (!isOpen) return null

  const categories = ['database', 'document', 'api'] as const
  const connectorsByCategory = categories.map(cat => ({
    category: cat,
    connectors: CONNECTOR_REGISTRY.filter(c => c.category === cat)
  }))

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[110] flex items-center justify-center"
      >
        <div 
          className="fixed inset-0 bg-black/20 backdrop-blur-sm"
          onClick={onClose}
        />
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className={cn(
            "relative w-[900px] max-h-[90vh] overflow-y-auto rounded-xl",
            "bg-white dark:bg-gray-800",
            "border border-gray-200 dark:border-gray-700",
            "shadow-2xl p-6"
          )}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-xl font-semibold text-foreground">Select Source Type</h3>
              <p className="text-xs text-muted-foreground mt-1">
                Choose a data source to connect
              </p>
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center justify-center"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="space-y-6">
            {connectorsByCategory.map(({ category, connectors }) => (
              <div key={category}>
                <h4 className="text-sm font-semibold text-foreground mb-3 capitalize">{category}s</h4>
                <div className="grid grid-cols-3 gap-3">
                  {connectors.map((connector) => {
                    const Icon = connector.icon
                    return (
                      <button
                        key={connector.id}
                        onClick={() => {
                          onSelect(connector)
                          onClose()
                        }}
                        className={cn(
                          "p-4 rounded-lg border-2 transition-all text-left",
                          "border-gray-200 dark:border-gray-700 hover:border-blue-400 dark:hover:border-blue-600",
                          "bg-white dark:bg-gray-800 hover:bg-blue-50/50 dark:hover:bg-blue-900/20"
                        )}
                      >
                        <div className={cn(
                          "w-10 h-10 rounded-lg flex items-center justify-center mb-2",
                          category === 'database' && "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400",
                          category === 'document' && "bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400",
                          category === 'api' && "bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400"
                        )}>
                          <Icon className="w-5 h-5" />
                        </div>
                        <p className="text-sm font-medium text-foreground mb-1">{connector.name}</p>
                        <p className="text-xs text-muted-foreground line-clamp-2">{connector.description}</p>
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}

interface ConnectionFormModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: () => void
  connector: ConnectorDefinition | null
  formData: Record<string, any>
  setFormData: (data: Record<string, any>) => void
  selectedAuthMethod: string
  setSelectedAuthMethod: (method: string) => void
  isDark: boolean
}

export function ConnectionFormModal({
  isOpen,
  onClose,
  onSubmit,
  connector,
  formData,
  setFormData,
  selectedAuthMethod,
  setSelectedAuthMethod,
  isDark
}: ConnectionFormModalProps) {
  if (!isOpen || !connector) return null

  const currentAuthMethod = connector.authMethods.find(a => a.type === selectedAuthMethod) || connector.authMethods[0]
  const allFields = [...connector.fields, ...(currentAuthMethod?.fields || [])]
  const isFormValid = formData.name && allFields.filter(f => f.required).every(f => formData[f.key])

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[110] flex items-center justify-center"
      >
        <div 
          className="fixed inset-0 bg-black/20 backdrop-blur-sm"
          onClick={onClose}
        />
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className={cn(
            "relative w-[1000px] max-h-[90vh] overflow-hidden rounded-xl flex",
            "bg-white dark:bg-gray-800",
            "border border-gray-200 dark:border-gray-700",
            "shadow-2xl"
          )}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Left Panel - Form */}
          <div className="flex-1 p-6 overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="text-xl font-semibold text-foreground">Set up the source</h3>
                <p className="text-xs text-muted-foreground mt-1">
                  Configure your {connector.name} connection
                </p>
              </div>
              <button
                onClick={onClose}
                className="w-8 h-8 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center justify-center"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-6">
              {/* Source Type Display */}
              <div className="flex items-center gap-3 p-3 rounded-lg bg-gray-50 dark:bg-gray-900/30">
                {(() => {
                  const Icon = connector.icon
                  return (
                    <div className={cn(
                      "w-10 h-10 rounded-lg flex items-center justify-center",
                      connector.category === 'database' && "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400",
                      connector.category === 'document' && "bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400",
                      connector.category === 'api' && "bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400"
                    )}>
                      <Icon className="w-5 h-5" />
                    </div>
                  )
                })()}
                <div>
                  <p className="text-sm font-medium text-foreground">Source type</p>
                  <p className="text-xs text-muted-foreground">{connector.name}</p>
                </div>
              </div>

              {/* Connection Name */}
              <div>
                <label className="text-xs font-medium text-foreground mb-1.5 block">
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={formData.name || ''}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Pick a name to help you identify this source"
                  className={cn(
                    "h-9 text-xs",
                    isDark 
                      ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                      : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                  )}
                />
              </div>

              {/* Authentication Method Selection */}
              {connector.authMethods.length > 1 && (
                <div>
                  <label className="text-xs font-medium text-foreground mb-1.5 block">
                    Authentication:
                  </label>
                  <div className="relative">
                    <select
                      value={selectedAuthMethod}
                      onChange={(e) => setSelectedAuthMethod(e.target.value)}
                      className={cn(
                        "h-9 w-full px-3 pr-8 rounded-lg text-xs border appearance-none cursor-pointer",
                        isDark 
                          ? "bg-white/4 border-white/8 text-foreground" 
                          : "bg-white border-black/8 text-foreground"
                      )}
                    >
                      {connector.authMethods.map(auth => (
                        <option key={auth.type} value={auth.type}>{auth.label}</option>
                      ))}
                    </select>
                    <svg
                      className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </div>
              )}

              {/* Dynamic Fields */}
              <div className="space-y-4">
                {connector.fields.map(field => (
                  <DynamicFormField
                    key={field.key}
                    field={field}
                    value={formData[field.key]}
                    onChange={(value) => setFormData({ ...formData, [field.key]: value })}
                    isDark={isDark}
                  />
                ))}

                {/* Auth Method Fields */}
                {currentAuthMethod && currentAuthMethod.fields.map(field => (
                  <DynamicFormField
                    key={field.key}
                    field={field}
                    value={formData[field.key]}
                    onChange={(value) => setFormData({ ...formData, [field.key]: value })}
                    isDark={isDark}
                  />
                ))}
              </div>

              {/* Description */}
              <div>
                <label className="text-xs font-medium text-foreground mb-1.5 block">
                  Description
                </label>
                <textarea
                  value={formData.description || ''}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="Optional description"
                  rows={3}
                  className={cn(
                    "w-full rounded-lg text-xs p-2.5 resize-none",
                    isDark 
                      ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                      : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                  )}
                />
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-3 pt-6 mt-6 border-t">
              <button
                onClick={onClose}
                className={cn(
                  "px-4 py-2 rounded-lg text-sm font-medium",
                  "hover:bg-gray-100 dark:hover:bg-gray-700",
                  "transition-colors"
                )}
              >
                Cancel
              </button>
              <button
                onClick={onSubmit}
                disabled={!isFormValid}
                className={cn(
                  "px-4 py-2 rounded-lg text-sm font-medium",
                  "bg-blue-500 hover:bg-blue-600 text-white",
                  "disabled:opacity-50 disabled:cursor-not-allowed",
                  "transition-colors flex items-center gap-2"
                )}
              >
                <Link2 className="w-4 h-4" />
                Set up source
              </button>
            </div>
          </div>

          {/* Right Panel - Instructions */}
          <div className={cn(
            "w-80 border-l p-6 overflow-y-auto",
            "bg-gray-50 dark:bg-gray-900/50",
            "border-gray-200 dark:border-gray-700"
          )}>
            <div className="mb-4">
              <p className="text-xs font-semibold text-foreground mb-2">For Airbyte OSS</p>
              <div className="space-y-3 text-xs text-muted-foreground">
                <div>
                  <p className="font-medium text-foreground mb-1">Setup Instructions:</p>
                  <ol className="list-decimal list-inside space-y-1 ml-2">
                    <li>Enable the required APIs for your account.</li>
                    {currentAuthMethod?.instructions && (
                      <li className="mt-2">
                        <div className={cn(
                          "p-2 rounded bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 mb-2"
                        )}>
                          <Info className="w-3 h-3 inline mr-1" />
                          <span className="text-[10px]">{currentAuthMethod.instructions}</span>
                        </div>
                      </li>
                    )}
                    <li>Go to the Airbyte UI and in the left navigation bar, click source.</li>
                    <li>On the Set up the source page, select {connector.name}.</li>
                    <li>For Name, enter a name for the {connector.name} connection.</li>
                    <li>Authenticate your account via {currentAuthMethod?.label || 'the selected method'}.</li>
                    {connector.fields.find(f => f.key.includes('link') || f.key.includes('url')) && (
                      <li>Enter the link or URL to your {connector.name.toLowerCase()} resource.</li>
                    )}
                  </ol>
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}

