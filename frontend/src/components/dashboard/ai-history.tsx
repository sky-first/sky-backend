"use client"

import { useState, useMemo, useEffect } from "react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { 
    Search, 
    MessageSquare, 
    Pin, 
    MoreHorizontal, 
    Copy, 
    Trash2, 
    BookOpen,
    Clock,
    Filter,
    X,
    Loader2
} from "lucide-react"
import { motion, AnimatePresence } from "framer-motion"
import { cn } from "@/lib/utils"
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useAIHistoryStore } from "@/store/ai-history-store"

type FilterType = "all" | "today" | "week" | "pinned"

export function AIHistory() {
    const [searchTerm, setSearchTerm] = useState("")
    const [filter, setFilter] = useState<FilterType>("all")
    const { 
        historyItems, 
        isLoading, 
        error,
        fetchHistory, 
        deleteHistory, 
        pinHistory, 
        unpinHistory,
        exportHistory 
    } = useAIHistoryStore()

    // Fetch history on mount and when filter changes
    useEffect(() => {
        const filterParam = filter === "all" ? undefined : filter as "today" | "week" | "pinned"
        fetchHistory({
            filter: filterParam,
            search: searchTerm || undefined,
            limit: 100,
        })
    }, [filter, searchTerm, fetchHistory])

    // Filter and search logic (backend handles most filtering, but we do client-side search for better UX)
    const filteredItems = useMemo(() => {
        let filtered = [...historyItems]

        // Apply client-side search (backend also does search, but this provides instant feedback)
        if (searchTerm) {
            filtered = filtered.filter(item => 
                item.query.toLowerCase().includes(searchTerm.toLowerCase()) ||
                item.preview.toLowerCase().includes(searchTerm.toLowerCase()) ||
                item.tags.some(tag => tag.toLowerCase().includes(searchTerm.toLowerCase()))
            )
        }

        // Sort: pinned first, then by date
        return filtered.sort((a, b) => {
            if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
            return new Date(b.date).getTime() - new Date(a.date).getTime()
        })
    }, [historyItems, searchTerm])

    const handlePin = async (id: string) => {
        const item = historyItems.find(h => h.id === id)
        if (!item) return
        
        try {
            if (item.pinned) {
                await unpinHistory(id)
            } else {
                await pinHistory(id)
            }
        } catch (error) {
            console.error('Error pinning/unpinning:', error)
        }
    }

    const handleCopy = (text: string) => {
        navigator.clipboard.writeText(text)
        // Could add toast notification here
    }

    const handleDelete = async (id: string) => {
        try {
            await deleteHistory(id)
        } catch (error) {
            console.error('Error deleting history:', error)
        }
    }

    const handleExport = async () => {
        try {
            await exportHistory()
        } catch (error) {
            console.error('Error exporting history:', error)
        }
    }

    const formatDate = (dateString: string) => {
        try {
            const date = new Date(dateString)
            const now = new Date()
            const diffMs = now.getTime() - date.getTime()
            const diffMins = Math.floor(diffMs / 60000)
            const diffHours = Math.floor(diffMs / 3600000)
            const diffDays = Math.floor(diffMs / 86400000)

            if (diffMins < 1) return 'just now'
            if (diffMins < 60) return `${diffMins} min${diffMins > 1 ? 's' : ''} ago`
            if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`
            if (diffDays < 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`
            return date.toLocaleDateString()
        } catch {
            return dateString
        }
    }

    const handleReuse = (query: string) => {
        // This would integrate with the AI search bar
        // For now, we'll just log it
        console.log("Reusing query:", query)
    }

    const getCategoryColor = (category: string) => {
        const colors: Record<string, string> = {
            Finance: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20",
            Marketing: "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20",
            Sales: "bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/20",
            General: "bg-gray-500/10 text-gray-600 dark:text-gray-400 border-gray-500/20",
            Logistics: "bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/20",
        }
        return colors[category] || colors.General
    }

    return (
        <div className="flex flex-col h-full bg-card/50 backdrop-blur-xl overflow-hidden">
            {/* Header */}
            <div className="px-4 py-4 border-b border-border/50 bg-gradient-to-r from-background to-background/50">
                <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                        <div className="p-2 rounded-lg bg-gradient-to-br from-purple-500/20 to-primary/20">
                            <BookOpen className="w-5 h-5 text-purple-500" />
                        </div>
                        <div>
                            <h2 className="font-bold text-lg bg-gradient-to-r from-primary to-purple-600 bg-clip-text text-transparent">
                                AI History
                            </h2>
                            <p className="text-xs text-muted-foreground">{filteredItems.length} items</p>
                        </div>
                    </div>
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-8 w-8">
                                <MoreHorizontal className="w-4 h-4" />
                            </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem>Clear History</DropdownMenuItem>
                            <DropdownMenuItem>Export History</DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>

                {/* Search */}
                <div className="relative mb-3">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input 
                        placeholder="Search history..." 
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="pl-9 pr-8 bg-background/50 border-border/50 focus:border-primary h-9" 
                    />
                    {searchTerm && (
                        <Button
                            variant="ghost"
                            size="icon"
                            className="absolute right-1 top-1/2 -translate-y-1/2 h-6 w-6"
                            onClick={() => setSearchTerm("")}
                        >
                            <X className="w-3 h-3" />
                        </Button>
                    )}
                </div>

                {/* Filters */}
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 flex-1">
                        {(["all", "today", "week", "pinned"] as FilterType[]).map((filterType) => (
                            <Button
                                key={filterType}
                                variant={filter === filterType ? "default" : "ghost"}
                                size="sm"
                                className={cn(
                                    "h-8 px-3 text-xs font-medium capitalize transition-all",
                                    filter === filterType 
                                        ? "bg-primary text-primary-foreground shadow-sm" 
                                        : "hover:bg-accent/50"
                                )}
                                onClick={() => setFilter(filterType)}
                            >
                                {filterType === "all" && <Filter className="w-3.5 h-3.5 mr-1.5" />}
                                {filterType === "today" && <Clock className="w-3.5 h-3.5 mr-1.5" />}
                                {filterType === "pinned" && <Pin className="w-3.5 h-3.5 mr-1.5" />}
                                {filterType}
                            </Button>
                        ))}
                    </div>
                </div>
            </div>

            {/* History List */}
            <div className="flex-1 min-h-0 overflow-hidden">
                <ScrollArea className="h-full custom-scrollbar">
                    <div className="p-4">
                    {filteredItems.length > 0 ? (
                        <div className="space-y-3">
                            <AnimatePresence>
                                {filteredItems.map((item, index) => {
                                    const isPinned = item.pinned
                                    return (
                                        <motion.div
                                            key={item.id}
                                            initial={{ opacity: 0, y: 20 }}
                                            animate={{ opacity: 1, y: 0 }}
                                            exit={{ opacity: 0, scale: 0.95 }}
                                            transition={{ delay: index * 0.03 }}
                                            className="group relative"
                                        >
                                            <div className={cn(
                                                "flex flex-col gap-3 p-4 rounded-xl border bg-card/80 backdrop-blur-sm",
                                                "hover:bg-accent/50 hover:border-primary/30 hover:shadow-lg",
                                                "transition-all duration-200 cursor-pointer",
                                                isPinned && "border-primary/30 bg-primary/5"
                                            )}
                                            onClick={() => handleReuse(item.query)}
                                            >
                                                {/* Header */}
                                                <div className="flex items-start justify-between gap-2">
                                                    <div className="flex items-center gap-2 flex-1 min-w-0">
                                                        <MessageSquare className={cn(
                                                            "w-4 h-4 flex-shrink-0 transition-colors",
                                                            isPinned ? "text-primary" : "text-muted-foreground"
                                                        )} />
                                                        <span className="text-xs text-muted-foreground whitespace-nowrap">
                                                            {formatDate(item.date)}
                                                        </span>
                                                        {item.category && (
                                                            <Badge 
                                                                variant="outline" 
                                                                className={cn(
                                                                    "text-[10px] px-2 py-0 border",
                                                                    getCategoryColor(item.category)
                                                                )}
                                                            >
                                                                {item.category}
                                                            </Badge>
                                                        )}
                                                    </div>
                                                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            className="h-7 w-7"
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                handlePin(item.id)
                                                            }}
                                                        >
                                                            <Pin className={cn(
                                                                "w-3.5 h-3.5",
                                                                isPinned && "fill-primary text-primary"
                                                            )} />
                                                        </Button>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            className="h-7 w-7"
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                handleCopy(item.query)
                                                            }}
                                                        >
                                                            <Copy className="w-3.5 h-3.5" />
                                                        </Button>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            className="h-7 w-7 hover:bg-destructive/10 hover:text-destructive"
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                handleDelete(item.id)
                                                            }}
                                                        >
                                                            <Trash2 className="w-3.5 h-3.5" />
                                                        </Button>
                                                    </div>
                                                </div>

                                                {/* Query */}
                                                <p className="text-sm font-semibold leading-snug text-foreground line-clamp-2">
                                                    {item.query}
                                                </p>

                                                {/* Preview */}
                                                <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">
                                                    {item.preview}
                                                </p>

                                                {/* Tags */}
                                                <div className="flex flex-wrap gap-1.5">
                                                    {item.tags.map(tag => (
                                                        <Badge 
                                                            key={tag} 
                                                            variant="secondary" 
                                                            className="text-[10px] px-2 py-0.5 font-normal"
                                                        >
                                                            {tag}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            </div>
                                        </motion.div>
                                    )
                                })}
                            </AnimatePresence>
                        </div>
                    ) : (
                        <motion.div
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="flex flex-col items-center justify-center h-64 text-center"
                        >
                            <MessageSquare className="w-12 h-12 text-muted-foreground/30 mb-4" />
                            <p className="text-sm font-medium text-foreground mb-1">
                                {searchTerm ? "No results found" : "No history yet"}
                            </p>
                            <p className="text-xs text-muted-foreground">
                                {searchTerm 
                                    ? `Try searching for something else` 
                                    : "Your AI interactions will appear here"}
                            </p>
                        </motion.div>
                    )}
                    </div>
                </ScrollArea>
            </div>
        </div>
    )
}
