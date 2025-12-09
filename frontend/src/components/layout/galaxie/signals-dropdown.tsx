"use client"

import { motion, AnimatePresence } from "framer-motion"
import { Radio, Bell, Sparkles, Share2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface SignalsDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
}

export function SignalsDropdown({ isOpen, onOpenChange, onClose }: SignalsDropdownProps) {
  // Mock signals data - in real implementation, this would come from a store/API
  const signals = [
    { id: '1', type: 'widget', message: 'Widget Update', timestamp: '2 hours ago' },
    { id: '2', type: 'ai', message: 'AI Task Completed', timestamp: '5 hours ago' },
    { id: '3', type: 'share', message: 'New shared planet', timestamp: '1 day ago' },
  ]

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
            "absolute left-full top-0 ml-2 w-64",
            "bg-white dark:bg-gray-900",
            "rounded-xl shadow-xl",
            "border border-gray-200 dark:border-gray-800",
            "overflow-hidden z-[60]",
            "pointer-events-auto"
          )}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="p-3 space-y-1">
            {signals.map((signal) => {
              const getIcon = () => {
                switch (signal.type) {
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

              return (
                <button
                  key={signal.id}
                  onClick={() => {
                    onOpenChange(false)
                    onClose?.()
                  }}
                  className={cn(
                    "w-full text-left px-3 py-2 rounded-lg",
                    "hover:bg-gray-100 dark:hover:bg-gray-800",
                    "transition-all duration-200"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <div className="text-gray-500 dark:text-gray-400">
                      {getIcon()}
                    </div>
                    <div className="flex-1">
                      <div className="text-sm text-gray-700 dark:text-gray-300">
                        {signal.message}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">
                        {signal.timestamp}
                      </div>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

