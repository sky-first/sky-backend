"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Radio, Bell, Sparkles, Share2, Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

interface SignalsDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}

export function SignalsDropdown({ isOpen, onOpenChange, onClose, onMouseEnter, onMouseLeave }: SignalsDropdownProps) {
  const [searchQuery, setSearchQuery] = useState("")
  
  // Mock signals data - in real implementation, this would come from a store/API
  const signals = [
    { id: '1', type: 'widget', message: 'Widget Update', timestamp: '2 hours ago' },
    { id: '2', type: 'ai', message: 'AI Task Completed', timestamp: '5 hours ago' },
    { id: '3', type: 'share', message: 'New shared planet', timestamp: '1 day ago' },
  ]

  const filteredSignals = signals.filter(signal =>
    signal.message.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const getIcon = (type: string) => {
    switch (type) {
      case 'widget':
        return <Bell className="w-4 h-4" />
      case 'ai':
        return <Sparkles className="w-4 h-4" />
      case 'share':
        return <Share2 className="w-4 h-4" />
      default:
        return <Radio className="w-4 h-4" />
    }
  }

  if (!isOpen) return null

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -10 }}
          transition={{ duration: 0.2 }}
          className={cn(
            "w-80 flex flex-col flex-shrink-0",
            "bg-white dark:bg-gray-900",
            "border-l border-gray-200 dark:border-gray-800",
            "overflow-hidden",
            "pointer-events-auto"
          )}
          onClick={(e) => e.stopPropagation()}
          onMouseEnter={onMouseEnter}
          onMouseLeave={onMouseLeave}
        >
          {/* Header */}
          <div className="p-5 border-b border-gray-200 dark:border-gray-800">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
              Signals
            </h2>
            
            {/* Search Bar */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <Input
                type="text"
                placeholder="Filter signals..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className={cn(
                  "pl-9 h-9 w-full rounded-lg border-2 border-blue-500",
                  "bg-white dark:bg-gray-800",
                  "text-gray-900 dark:text-white",
                  "placeholder:text-gray-400 dark:placeholder:text-gray-500",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                )}
              />
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-4">
            {/* SIGNALS Section */}
            <div>
              <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 px-2">
                SIGNALS
              </div>
              
              {filteredSignals.length === 0 ? (
                <div className="px-2 py-8 text-center text-sm text-gray-500 dark:text-gray-400">
                  No signals found
                </div>
              ) : (
                <div className="space-y-1">
                  {filteredSignals.map((signal) => (
                    <button
                      key={signal.id}
                      onClick={() => {
                        onOpenChange(false)
                        onClose?.()
                      }}
                      className={cn(
                        "w-full text-left px-3 py-2.5 rounded-lg",
                        "transition-all duration-200",
                        "hover:bg-gray-50 dark:hover:bg-gray-800",
                        "flex items-center gap-3 group"
                      )}
                    >
                      <div className="text-gray-500 dark:text-gray-400 shrink-0">
                        {getIcon(signal.type)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-gray-900 dark:text-white">
                          {signal.message}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {signal.timestamp}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

