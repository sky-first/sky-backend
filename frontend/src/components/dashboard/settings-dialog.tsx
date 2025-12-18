"use client"

import { useState, useMemo } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { 
    X, Search, Settings, Database, Shield, 
    Users, Bell, Globe, Key, Lock, Palette,
    Plus, Eye, Trash2, Edit2, ChevronLeft, ChevronRight,
    MoreVertical, Filter, RefreshCw, ArrowUpDown, Info,
    UserPlus, CheckCircle2, Clock, MoreHorizontal, ChevronDown, Link2
} from "lucide-react"
import { useSettingsStore } from "@/store/settings-store"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"
import { DataCatalogSection, SpacesSection, CrewsSection, UsersSection, PermissionsSection } from "./settings-sections"

const CATEGORIES = [
    {
        label: "CONFIGURATION",
        items: [
            { id: 'data-catalog', label: 'Data Catalog', icon: Database },
            { id: 'spaces', label: 'Spaces', icon: Users },
            { id: 'crews', label: 'Crews', icon: Users },
            { id: 'users', label: 'Users', icon: Users },
            { id: 'permissions', label: 'Permissions', icon: Shield },
            { id: 'notifications', label: 'Notifications', icon: Bell },
            { id: 'integrations', label: 'Integrations', icon: Globe },
            { id: 'api-keys', label: 'API Keys', icon: Key },
            { id: 'security', label: 'Security', icon: Lock },
        ]
    },
    {
        label: "APPEARANCE",
        items: [
            { id: 'theme', label: 'Theme', icon: Palette },
        ]
    }
]

export function SettingsDialog() {
    const {
        isOpen,
        close,
        selectedCategory,
        setSelectedCategory,
        searchQuery,
        setSearchQuery,
    } = useSettingsStore()
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'

    const currentCategory = useMemo(() => {
        for (const category of CATEGORIES) {
            const item = category.items.find(item => item.id === selectedCategory)
            if (item) return item
        }
        // If category is not found, default to data-catalog
        const defaultCategory = CATEGORIES[0].items.find(item => item.id === 'data-catalog') || CATEGORIES[0].items[0]
        // Update store if category is invalid
        if (selectedCategory !== defaultCategory.id) {
            setSelectedCategory(defaultCategory.id)
        }
        return defaultCategory
    }, [selectedCategory, setSelectedCategory])

    if (!isOpen) return null

    const modalStyle = {
        borderRadius: "1rem",
        border: isDark 
            ? "1px solid rgba(255, 255, 255, 0.08)" 
            : "1px solid rgba(0, 0, 0, 0.08)",
        background: isDark 
            ? "rgba(15, 23, 42, 0.98)" 
            : "rgba(255, 255, 255, 0.98)",
        backdropFilter: "blur(40px) saturate(180%)",
        WebkitBackdropFilter: "blur(40px) saturate(180%)",
        boxShadow: isDark 
            ? "0 20px 60px rgba(0, 0, 0, 0.5), 0 4px 16px rgba(0, 0, 0, 0.3)" 
            : "0 20px 60px rgba(0, 0, 0, 0.15), 0 4px 16px rgba(0, 0, 0, 0.1)",
    }

    return (
        <AnimatePresence>
            <div className="fixed inset-0 z-[100] pointer-events-auto">
                {/* Backdrop */}
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.15 }}
                    className="fixed inset-0 bg-black/5 backdrop-blur-[1px]"
                    onClick={close}
                />

                {/* Modal */}
                <motion.div
                    initial={{ opacity: 0, scale: 0.96, y: 20 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.96, y: 20 }}
                    transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                    className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[1200px] h-[750px] flex overflow-hidden rounded-2xl"
                    style={modalStyle}
                    onClick={(e) => e.stopPropagation()}
                >
                    {/* Left Sidebar */}
                    <div className={cn(
                        "w-52 flex flex-col flex-shrink-0",
                        isDark ? "bg-gray-900/30 border-r border-white/5" : "bg-gray-50/60 border-r border-black/5"
                    )}>
                        <div className="p-5 border-b" style={{ borderColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }}>
                            <div className="flex items-center gap-2.5">
                                <div className={cn(
                                    "w-9 h-9 rounded-lg flex items-center justify-center",
                                    "bg-blue-500/10 border border-blue-500/20"
                                )}>
                                    <Settings className="w-5 h-5 text-blue-500" />
                                </div>
                                <div>
                                    <h2 className="text-base font-semibold text-foreground leading-tight">Settings</h2>
                                    <p className="text-[10px] text-muted-foreground leading-tight mt-0.5">Configuration</p>
                                </div>
                            </div>
                        </div>

                        <div className="flex-1 overflow-y-auto p-4 space-y-5">
                            {CATEGORIES.map((category) => (
                                <div key={category.label}>
                                    <h3 className={cn(
                                        "text-[9px] font-semibold uppercase tracking-wider mb-2.5 px-2.5",
                                        isDark ? "text-white/25" : "text-gray-400"
                                    )}>
                                        {category.label}
                                    </h3>
                                    <div className="space-y-0.5">
                                        {category.items.map((item) => {
                                            const Icon = item.icon
                                            return (
                                                <button
                                                    key={item.id}
                                                    onClick={() => setSelectedCategory(item.id)}
                                                    className={cn(
                                                        "w-full text-left px-2.5 py-2 rounded-md text-xs transition-all duration-200",
                                                        "flex items-center gap-2 group",
                                                        selectedCategory === item.id
                                                            ? "bg-blue-500/12 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 font-medium"
                                                            : "text-foreground/60 hover:text-foreground hover:bg-gray-100/50 dark:hover:bg-white/5",
                                                    )}
                                                >
                                                    <Icon className="w-3.5 h-3.5 shrink-0" />
                                                    <span className="text-xs leading-tight">{item.label}</span>
                                                </button>
                                            )
                                        })}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Main Content */}
                    <div className="flex-1 flex flex-col overflow-hidden">
                        {/* Top Bar */}
                        <div className={cn(
                            "px-5 py-4 border-b flex items-center justify-between",
                            isDark ? "border-white/5" : "border-black/5"
                        )}>
                            <div>
                                <h1 className="text-xl font-semibold text-foreground mb-0.5">
                                    {currentCategory.label}
                                </h1>
                                <p className="text-[11px] text-muted-foreground">
                                    Configure {currentCategory.label.toLowerCase()} settings
                                </p>
                            </div>
                            <button
                                onClick={close}
                                className={cn(
                                    "w-8 h-8 rounded-lg flex items-center justify-center",
                                    "hover:bg-gray-100/50 dark:hover:bg-white/5",
                                    "transition-colors"
                                )}
                                aria-label="Close settings"
                            >
                                <X className="w-4 h-4 text-foreground/60" />
                            </button>
                        </div>

                        {/* Content Area */}
                        <div className={cn(
                            "flex-1",
                            selectedCategory === 'data-catalog' ? "overflow-hidden" : "overflow-y-auto"
                        )}>
                            {/* Settings Content */}
                            <div className={selectedCategory === 'data-catalog' ? "h-full" : ""}>
                                {selectedCategory === 'data-catalog' && <DataCatalogSection isDark={isDark} />}
                                {selectedCategory === 'spaces' && <SpacesSection isDark={isDark} />}
                                {selectedCategory === 'crews' && <CrewsSection isDark={isDark} />}
                                {selectedCategory === 'users' && <UsersSection isDark={isDark} />}
                                {selectedCategory === 'permissions' && <PermissionsSection isDark={isDark} />}

                                {/* Placeholder for other categories */}
                                {!['data-catalog', 'spaces', 'crews', 'users', 'permissions'].includes(selectedCategory) && (
                                    <div className="p-5 space-y-4">
                                        <div className="mb-5">
                                            <div className="relative">
                                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
                                                <Input
                                                    type="text"
                                                    placeholder="Search settings..."
                                                    value={searchQuery}
                                                    onChange={(e) => setSearchQuery(e.target.value)}
                                                    className={cn(
                                                        "pl-9 h-9 text-xs",
                                                        isDark 
                                                            ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                            : "bg-white/60 border-black/8 focus:border-black/15 focus:bg-white"
                                                    )}
                                                />
                                            </div>
                                        </div>
                                        <h3 className="text-sm font-semibold text-foreground">{currentCategory.label}</h3>
                                        <p className="text-xs text-muted-foreground">
                                            {currentCategory.label} settings will be available here.
                                        </p>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </motion.div>
            </div>
        </AnimatePresence>
    )
}
