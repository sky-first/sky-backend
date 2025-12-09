"use client"

import { useState } from "react"
import { Settings } from "lucide-react"
import { cn } from "@/lib/utils"
import { motion, AnimatePresence } from "framer-motion"
import { useSettingsStore } from "@/store/settings-store"

export function HelpButton() {
    const [isHovered, setIsHovered] = useState(false)
    const { open } = useSettingsStore()

    const handleClick = () => {
        open()
    }

    return (
        <motion.button
            data-tour="help-button"
            onClick={handleClick}
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            className={cn(
                "fixed bottom-4 left-4 z-50",
                "w-12 h-12 rounded-full",
                "flex items-center justify-center",
                "bg-white dark:bg-gray-800",
                "border border-gray-200 dark:border-gray-700",
                "shadow-lg",
                "hover:shadow-xl",
                "transition-all duration-200",
                "focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2",
                "dark:focus:ring-offset-gray-900"
            )}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            aria-label="Settings"
        >
            <Settings 
                className={cn(
                    "w-6 h-6",
                    "text-gray-600 dark:text-gray-300"
                )} 
            />
            
            {/* Tooltip */}
            <AnimatePresence>
                {isHovered && (
                    <motion.div
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -10 }}
                        transition={{ duration: 0.15 }}
                        className={cn(
                            "absolute right-full mr-3 px-3 py-1.5 rounded-lg",
                            "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900",
                            "text-xs font-medium whitespace-nowrap",
                            "shadow-lg",
                            "pointer-events-none"
                        )}
                    >
                        Settings
                        <div className={cn(
                            "absolute left-full top-1/2 -translate-y-1/2",
                            "w-0 h-0 border-t-4 border-t-transparent border-b-4 border-b-transparent",
                            "border-l-4 border-l-gray-900 dark:border-l-gray-100"
                        )} />
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.button>
    )
}

