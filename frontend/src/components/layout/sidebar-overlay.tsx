"use client"

import { useEffect } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion, AnimatePresence } from "framer-motion"
import {
    LayoutDashboard,
    FolderKanban,
    Link2,
    Settings,
    HelpCircle,
    X,
    Bot,
    Sparkles
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSidebarStore } from "@/store/sidebar-store"
import { cn } from "@/lib/utils"
import { Separator } from "@/components/ui/separator"

const MAIN_NAV_ITEMS = [
    { icon: LayoutDashboard, label: "Dashboard", href: "/dashboard" },
    { icon: FolderKanban, label: "Projects", href: "/dashboard/projects" },
    { icon: Link2, label: "Connections", href: "/dashboard/connections" },
]

const AI_NAV_ITEMS = [
    { icon: Bot, label: "AI History", href: "/dashboard/ai-history", badge: "New" },
]

const SETTINGS_NAV_ITEMS = [
    { icon: Settings, label: "Settings", href: "/dashboard/settings" },
]

export function SidebarOverlay() {
    const pathname = usePathname()
    const { isOpen, setIsOpen } = useSidebarStore()

    // Close on escape key
    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && isOpen) {
                setIsOpen(false)
            }
        }
        document.addEventListener('keydown', handleEscape)
        return () => document.removeEventListener('keydown', handleEscape)
    }, [isOpen, setIsOpen])

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    {/* Backdrop */}
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[100]"
                        onClick={() => setIsOpen(false)}
                    />

                    {/* Sidebar */}
                    <motion.div
                        initial={{ x: -320 }}
                        animate={{ x: 0 }}
                        exit={{ x: -320 }}
                        transition={{ type: "spring", damping: 25, stiffness: 200 }}
                        className="fixed left-0 top-0 h-full w-80 bg-card/98 backdrop-blur-xl border-r border-border/50 shadow-2xl z-[101] flex flex-col pointer-events-auto"
                        onClick={(e) => e.stopPropagation()}
                    >
                        {/* Header */}
                        <div className="px-6 py-5 flex items-center justify-between border-b border-border/50 bg-gradient-to-r from-background to-background/50">
                            <div className="flex items-center gap-2">
                                <div className="p-2 rounded-lg bg-gradient-to-br from-primary/20 to-purple-600/20">
                                    <Sparkles className="w-5 h-5 text-primary" />
                                </div>
                                <span className="font-bold text-xl bg-gradient-to-r from-primary via-purple-600 to-primary bg-clip-text text-transparent bg-[length:200%_auto] animate-gradient">
                                    AI Nexus
                                </span>
                            </div>
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setIsOpen(false)}
                                className="h-9 w-9 rounded-lg hover:bg-destructive/10 hover:text-destructive transition-colors"
                            >
                                <X className="w-4 h-4" />
                            </Button>
                        </div>

                        {/* Navigation */}
                        <div className="flex-1 py-6 px-3 overflow-y-auto overflow-x-hidden custom-scrollbar">
                            {/* Main Navigation */}
                            <div className="space-y-1 mb-6">
                                {MAIN_NAV_ITEMS.map((item, index) => {
                                    const isActive = pathname === item.href
                                    return (
                                        <motion.div
                                            key={item.href}
                                            initial={{ opacity: 0, x: -20 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            transition={{ delay: index * 0.05 }}
                                        >
                                            <Link href={item.href} onClick={() => setIsOpen(false)}>
                                                <Button
                                                    variant="ghost"
                                                    className={cn(
                                                        "w-full justify-start px-4 py-3 h-auto rounded-xl transition-all duration-200 group relative",
                                                        isActive
                                                            ? "bg-gradient-to-r from-primary/10 to-purple-600/10 text-foreground shadow-sm"
                                                            : "hover:bg-accent/50 text-muted-foreground hover:text-foreground"
                                                    )}
                                                >
                                                    {/* Active Indicator */}
                                                    {isActive && (
                                                        <motion.div
                                                            layoutId={`activeIndicator-${item.href}`}
                                                            className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-gradient-to-b from-primary to-purple-600 rounded-r-full"
                                                            transition={{ type: "spring", stiffness: 500, damping: 30 }}
                                                        />
                                                    )}
                                                    <item.icon className={cn(
                                                        "w-5 h-5 mr-3 transition-all duration-200",
                                                        isActive ? "text-primary scale-110" : "group-hover:scale-110"
                                                    )} />
                                                    <span className={cn(
                                                        "font-medium text-sm transition-all duration-200",
                                                        isActive ? "font-semibold" : ""
                                                    )}>
                                                        {item.label}
                                                    </span>
                                                </Button>
                                            </Link>
                                        </motion.div>
                                    )
                                })}
                            </div>

                            {/* AI Section */}
                            <div className="mb-6">
                                <div className="px-4 mb-2">
                                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                                        AI Features
                                    </span>
                                </div>
                                <div className="space-y-1">
                                    {AI_NAV_ITEMS.map((item, index) => {
                                        const isActive = pathname === item.href
                                        return (
                                            <motion.div
                                                key={item.href}
                                                initial={{ opacity: 0, x: -20 }}
                                                animate={{ opacity: 1, x: 0 }}
                                                transition={{ delay: (MAIN_NAV_ITEMS.length + index) * 0.05 }}
                                            >
                                                <Link href={item.href} onClick={() => setIsOpen(false)}>
                                                    <Button
                                                        variant="ghost"
                                                        className={cn(
                                                            "w-full justify-start px-4 py-3 h-auto rounded-xl transition-all duration-200 group relative",
                                                            isActive
                                                                ? "bg-gradient-to-r from-purple-500/10 to-primary/10 text-foreground shadow-sm"
                                                                : "hover:bg-accent/50 text-muted-foreground hover:text-foreground"
                                                        )}
                                                    >
                                                        {/* Active Indicator */}
                                                        {isActive && (
                                                            <motion.div
                                                                layoutId={`activeIndicator-${item.href}`}
                                                                className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-gradient-to-b from-purple-500 to-primary rounded-r-full"
                                                                transition={{ type: "spring", stiffness: 500, damping: 30 }}
                                                            />
                                                        )}
                                                        <item.icon className={cn(
                                                            "w-5 h-5 mr-3 transition-all duration-200 text-purple-500",
                                                            isActive ? "scale-110" : "group-hover:scale-110"
                                                        )} />
                                                        <span className={cn(
                                                            "font-medium text-sm transition-all duration-200 flex-1",
                                                            isActive ? "font-semibold" : ""
                                                        )}>
                                                            {item.label}
                                                        </span>
                                                        {item.badge && (
                                                            <span className="ml-2 px-2 py-0.5 text-xs font-semibold bg-gradient-to-r from-purple-500 to-primary text-white rounded-full">
                                                                {item.badge}
                                                            </span>
                                                        )}
                                                    </Button>
                                                </Link>
                                            </motion.div>
                                        )
                                    })}
                                </div>
                            </div>

                            <Separator className="my-4" />

                            {/* Settings Section */}
                            <div className="space-y-1">
                                {SETTINGS_NAV_ITEMS.map((item, index) => {
                                    const isActive = pathname === item.href
                                    return (
                                        <motion.div
                                            key={item.href}
                                            initial={{ opacity: 0, x: -20 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            transition={{ delay: (MAIN_NAV_ITEMS.length + AI_NAV_ITEMS.length + index) * 0.05 }}
                                        >
                                            <Link href={item.href} onClick={() => setIsOpen(false)}>
                                                <Button
                                                    variant="ghost"
                                                    className={cn(
                                                        "w-full justify-start px-4 py-3 h-auto rounded-xl transition-all duration-200 group relative",
                                                        isActive
                                                            ? "bg-gradient-to-r from-primary/10 to-purple-600/10 text-foreground shadow-sm"
                                                            : "hover:bg-accent/50 text-muted-foreground hover:text-foreground"
                                                    )}
                                                >
                                                    {/* Active Indicator */}
                                                    {isActive && (
                                                        <motion.div
                                                            layoutId={`activeIndicator-${item.href}`}
                                                            className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-gradient-to-b from-primary to-purple-600 rounded-r-full"
                                                            transition={{ type: "spring", stiffness: 500, damping: 30 }}
                                                        />
                                                    )}
                                                    <item.icon className={cn(
                                                        "w-5 h-5 mr-3 transition-all duration-200",
                                                        isActive ? "text-primary scale-110" : "group-hover:scale-110"
                                                    )} />
                                                    <span className={cn(
                                                        "font-medium text-sm transition-all duration-200",
                                                        isActive ? "font-semibold" : ""
                                                    )}>
                                                        {item.label}
                                                    </span>
                                                </Button>
                                            </Link>
                                        </motion.div>
                                    )
                                })}
                            </div>
                        </div>

                        {/* Footer */}
                        <div className="px-3 py-4 border-t border-border/50 bg-gradient-to-r from-background to-background/50">
                            <Button 
                                variant="ghost" 
                                className="w-full justify-start px-4 py-3 h-auto rounded-xl hover:bg-accent/50 text-muted-foreground hover:text-foreground transition-all duration-200 group"
                            >
                                <HelpCircle className="w-5 h-5 mr-3 group-hover:scale-110 transition-transform duration-200" />
                                <span className="font-medium text-sm">Help & Support</span>
                            </Button>
                        </div>
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    )
}

