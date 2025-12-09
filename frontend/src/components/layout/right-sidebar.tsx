"use client"

import { useAIHistoryStore } from "@/store/ai-history-store"
import { AIHistory } from "@/components/dashboard/ai-history"
import { Button } from "@/components/ui/button"
import { X } from "lucide-react"
import { motion, AnimatePresence } from "framer-motion"
import { cn } from "@/lib/utils"

export function RightSidebar() {
    const { isOpen: isAIHistoryOpen, setIsOpen: setIsAIHistoryOpen } = useAIHistoryStore()

    // Agora só mostra AI History - WidgetCustomization foi removido
    if (!isAIHistoryOpen) {
        return null
    }

    return (
        <AnimatePresence>
            {isAIHistoryOpen && (
                <>
                    {/* Sidebar - apenas AI History */}
                    <motion.div
                        initial={{ x: 400 }}
                        animate={{ x: 0 }}
                        exit={{ x: 400 }}
                        transition={{ type: "spring", damping: 25, stiffness: 200 }}
                        className={cn(
                            "fixed right-0 top-0 h-full w-80 bg-card/98 backdrop-blur-xl border-l border-border/50 shadow-2xl z-[91] flex flex-col pointer-events-auto"
                        )}
                    >
                        <div className="absolute top-2 right-2 z-10">
                            <Button variant="ghost" size="icon" onClick={() => setIsAIHistoryOpen(false)}>
                                <X className="w-4 h-4" />
                            </Button>
                        </div>
                        <AIHistory />
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    )
}
