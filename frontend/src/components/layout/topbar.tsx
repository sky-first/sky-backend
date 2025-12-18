"use client"

import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import { useUserStore } from "@/store/user-store"
import { useSidebarStore } from "@/store/sidebar-store"
import { useRouter } from "next/navigation"
import { LogOut } from "lucide-react"
import { CreatePlanetDialog } from "@/components/workspaces/create-workspace-dialog"
import { ProfileDropdown } from "@/components/layout/galaxie/profile-dropdown"
import { useTheme } from "next-themes"
import { FileText, ChevronDown, ChevronRight, Sun, Moon, Plus, Settings, Star, Bell, HelpCircle, Mail, Copy, Download, Move, Eye, Radio, Clock, Users, Link2, Globe, UserPlus, Code, Lock, ChevronUp, Search, Menu, Share2, BookOpen, Video, MessageCircle, User } from "lucide-react"
import { cn } from "@/lib/utils"
import { usePlanetStore } from "@/store/planet-store"

// Design tokens - consistent spacing and styling
const TOPBAR_CONFIG = {
    spacing: {
        container: "top-4",
        gap: "gap-2",
        itemPadding: "px-3 py-1.5",
    },
    style: {
        borderRadius: "0.75rem",
        padding: "0.625rem 0.875rem",
        transition: "transition-all duration-200 ease-out",
    },
} as const

export function Topbar() {
    const { user, logout } = useUserStore()
    const { isOpen, setIsOpen } = useSidebarStore()
    const router = useRouter()
    const { theme, setTheme, resolvedTheme } = useTheme()
    const [mounted, setMounted] = useState(false)
    const [showCreatePlanetDialog, setShowCreatePlanetDialog] = useState(false)
    const { currentPlanet } = usePlanetStore()

    const [showShareMenu, setShowShareMenu] = useState(false)
    const [shareTab, setShareTab] = useState<'invite' | 'embed' | 'publish'>('invite')
    const [showProfileMenu, setShowProfileMenu] = useState(false)
    const [showNotifications, setShowNotifications] = useState(false)
    const [showSpacesMenu, setShowSpacesMenu] = useState(false)
    const [spacesFilter, setSpacesFilter] = useState("")
    const spacesMenuTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const [showStarredMenu, setShowStarredMenu] = useState(false)
    const [starredFilter, setStarredFilter] = useState("")
    const starredMenuTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const [showRecentMenu, setShowRecentMenu] = useState(false)
    const [recentFilter, setRecentFilter] = useState("")
    const recentMenuTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const [showCrewsMenu, setShowCrewsMenu] = useState(false)
    const [crewsFilter, setCrewsFilter] = useState("")
    const crewsMenuTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const [showHelpMenu, setShowHelpMenu] = useState(false)
    

    useEffect(() => {
        setMounted(true)
    }, [])

    // Close menus on escape key
    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                setShowShareMenu(false)
                setShowProfileMenu(false)
                setShowNotifications(false)
                setShowHelpMenu(false)
                setShowSpacesMenu(false)
                setShowStarredMenu(false)
                setShowRecentMenu(false)
                setShowCrewsMenu(false)
            }
        }
        document.addEventListener('keydown', handleEscape)
        return () => document.removeEventListener('keydown', handleEscape)
    }, [])

    // Cleanup timeouts on unmount
    useEffect(() => {
        return () => {
            if (spacesMenuTimeoutRef.current) {
                clearTimeout(spacesMenuTimeoutRef.current)
            }
            if (starredMenuTimeoutRef.current) {
                clearTimeout(starredMenuTimeoutRef.current)
            }
            if (recentMenuTimeoutRef.current) {
                clearTimeout(recentMenuTimeoutRef.current)
            }
            if (crewsMenuTimeoutRef.current) {
                clearTimeout(crewsMenuTimeoutRef.current)
            }
        }
    }, [])

    const userInitials = user?.name
        ?.split(" ")
        .map((n) => n[0])
        .join("")
        .slice(0, 2)
        .toUpperCase() || "U"

    const companyName = user?.role || "NovaTech Group"
    const currentTheme = resolvedTheme || theme || 'light'
    const isDark = currentTheme === 'dark'

    // Shared topbar container style
    const getTopbarStyle = () => ({
        borderRadius: TOPBAR_CONFIG.style.borderRadius,
        padding: TOPBAR_CONFIG.style.padding,
        border: isDark 
            ? "1px solid rgba(255, 255, 255, 0.08)" 
            : "1px solid rgba(0, 0, 0, 0.08)",
        background: isDark 
            ? "rgba(15, 23, 42, 0.35)" 
            : "rgba(255, 255, 255, 0.55)",
        backdropFilter: "blur(32px) saturate(180%)",
        WebkitBackdropFilter: "blur(32px) saturate(180%)",
        boxShadow: isDark 
            ? "0 4px 20px rgba(0, 0, 0, 0.25), 0 1px 4px rgba(0, 0, 0, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.05)" 
            : "0 4px 20px rgba(0, 0, 0, 0.08), 0 1px 4px rgba(0, 0, 0, 0.04), inset 0 1px 0 rgba(255, 255, 255, 0.8)",
    })

    // Item hover style
    const itemHoverClass = cn(
        "rounded-lg",
        TOPBAR_CONFIG.style.transition,
        isDark 
            ? "hover:bg-white/8 active:bg-white/12" 
            : "hover:bg-black/5 active:bg-black/10"
    )


    if (!mounted) return null

    return (
        <>
            {/* Left Section - User Avatar with Planet Menu */}
            <div
                className={cn(
                    "fixed left-4 top-4 flex items-center z-50 pointer-events-none"
                )}
                style={getTopbarStyle()}
                data-tour="topbar"
            >
                <div className={cn("flex items-center", TOPBAR_CONFIG.spacing.gap, "pointer-events-auto")}>
                    {/* Sky Button */}
                    <div className="relative">
                        <button
                            className={cn(
                                "flex items-center justify-center",
                                "h-8 px-3 rounded-lg",
                                "text-white font-semibold text-sm",
                                "transition-all duration-200",
                                "focus:outline-none focus:ring-2 focus:ring-yellow-400/30 focus:ring-offset-2",
                                "dark:focus:ring-offset-gray-900",
                                "relative overflow-hidden",
                                isOpen && "ring-2 ring-yellow-400/30"
                            )}
                            style={{
                                background: `
                                    linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 50%, #1a2f4f 100%),
                                    radial-gradient(2px 2px at 20% 30%, rgba(255, 255, 0, 0.4), transparent),
                                    radial-gradient(1.5px 1.5px at 60% 70%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1px 1px at 50% 50%, rgba(255, 255, 0, 0.35), transparent),
                                    radial-gradient(1.5px 1.5px at 80% 10%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(2px 2px at 90% 40%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 33% 55%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 15% 80%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 70% 20%, rgba(255, 255, 0, 0.3), transparent)
                                `,
                                backgroundColor: '#1e3a5f'
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = `
                                    linear-gradient(135deg, #2a4a6f 0%, #3d5a7f 50%, #2a3f5f 100%),
                                    radial-gradient(2px 2px at 20% 30%, rgba(255, 255, 0, 0.4), transparent),
                                    radial-gradient(1.5px 1.5px at 60% 70%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1px 1px at 50% 50%, rgba(255, 255, 0, 0.35), transparent),
                                    radial-gradient(1.5px 1.5px at 80% 10%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(2px 2px at 90% 40%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 33% 55%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 15% 80%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 70% 20%, rgba(255, 255, 0, 0.3), transparent)
                                `
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = `
                                    linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 50%, #1a2f4f 100%),
                                    radial-gradient(2px 2px at 20% 30%, rgba(255, 255, 0, 0.4), transparent),
                                    radial-gradient(1.5px 1.5px at 60% 70%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1px 1px at 50% 50%, rgba(255, 255, 0, 0.35), transparent),
                                    radial-gradient(1.5px 1.5px at 80% 10%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(2px 2px at 90% 40%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 33% 55%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 15% 80%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 70% 20%, rgba(255, 255, 0, 0.3), transparent)
                                `
                            }}
                            onClick={(e) => {
                                e.stopPropagation()
                                setIsOpen(!isOpen)
                            }}
                            aria-label="Sky"
                        >
                            Sky
                        </button>
                                            </div>

                    {/* Planet Name */}
                    <div className={cn("flex items-center", TOPBAR_CONFIG.spacing.gap, itemHoverClass, TOPBAR_CONFIG.spacing.itemPadding)} data-tour="planet-name">
                        <FileText 
                            className={cn(
                                "w-4 h-4 shrink-0",
                                isDark ? "text-white/90" : "text-gray-900"
                            )} 
                            aria-hidden="true"
                        />
                        <span
                                className={cn(
                                    "text-sm font-medium text-left",
                                    isDark 
                                    ? "text-white/90" 
                                    : "text-gray-900"
                                )}
                            title="Current planet"
                            aria-label={`Current planet: ${currentPlanet?.name || "No planet selected"}`}
                            >
                            {currentPlanet?.name || "No planet selected"}
                        </span>
                    </div>

                </div>
            </div>

            {/* Right Section - Action Buttons */}
            <div
                className={cn(
                    "fixed right-4 flex items-center z-50 pointer-events-none",
                    TOPBAR_CONFIG.spacing.container
                )}
                style={getTopbarStyle()}
                data-tour="user-menu"
            >
                <div className={cn("flex items-center", TOPBAR_CONFIG.spacing.gap, "pointer-events-auto relative")}>
                    {/* Share Button - Moved to left */}
                    <div className="relative">
                        <button
                            className={cn(
                                "flex items-center justify-center",
                                "h-8 px-3 rounded-lg",
                                "text-white font-medium",
                                "transition-all duration-200",
                                "focus:outline-none focus:ring-2 focus:ring-yellow-400/30 focus:ring-offset-2",
                                "dark:focus:ring-offset-gray-900",
                                "shadow-sm hover:shadow-md",
                                "relative overflow-hidden",
                                showShareMenu && "ring-2 ring-yellow-400/30"
                            )}
                            style={{
                                background: `
                                    linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 50%, #1a2f4f 100%),
                                    radial-gradient(2px 2px at 20% 30%, rgba(255, 255, 0, 0.4), transparent),
                                    radial-gradient(1.5px 1.5px at 60% 70%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1px 1px at 50% 50%, rgba(255, 255, 0, 0.35), transparent),
                                    radial-gradient(1.5px 1.5px at 80% 10%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(2px 2px at 90% 40%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 33% 55%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 15% 80%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 70% 20%, rgba(255, 255, 0, 0.3), transparent)
                                `,
                                backgroundColor: '#1e3a5f'
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = `
                                    linear-gradient(135deg, #2a4a6f 0%, #3d5a7f 50%, #2a3f5f 100%),
                                    radial-gradient(2px 2px at 20% 30%, rgba(255, 255, 0, 0.4), transparent),
                                    radial-gradient(1.5px 1.5px at 60% 70%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1px 1px at 50% 50%, rgba(255, 255, 0, 0.35), transparent),
                                    radial-gradient(1.5px 1.5px at 80% 10%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(2px 2px at 90% 40%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 33% 55%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 15% 80%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 70% 20%, rgba(255, 255, 0, 0.3), transparent)
                                `
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = `
                                    linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 50%, #1a2f4f 100%),
                                    radial-gradient(2px 2px at 20% 30%, rgba(255, 255, 0, 0.4), transparent),
                                    radial-gradient(1.5px 1.5px at 60% 70%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1px 1px at 50% 50%, rgba(255, 255, 0, 0.35), transparent),
                                    radial-gradient(1.5px 1.5px at 80% 10%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(2px 2px at 90% 40%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 33% 55%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 15% 80%, rgba(255, 255, 0, 0.25), transparent),
                                    radial-gradient(1px 1px at 70% 20%, rgba(255, 255, 0, 0.3), transparent)
                                `
                            }}
                            onClick={(e) => {
                                e.stopPropagation()
                                // Close all other menus when opening share menu
                                setShowNotifications(false)
                                setShowProfileMenu(false)
                                setShowHelpMenu(false)
                                setShowShareMenu(!showShareMenu)
                            }}
                            aria-label="Share"
                            title="Share"
                        >
                            <span className="text-sm font-medium">
                                Share
                            </span>
                        </button>

                        {/* Share Menu Dropdown */}
                        {showShareMenu && (
                            <>
                                {/* Overlay to close on outside click */}
                                <div
                                    className="fixed inset-0 z-40"
                                    onClick={() => setShowShareMenu(false)}
                                />
                                <div 
                                    className={cn(
                                        "absolute right-0 top-full mt-3 w-[480px] max-w-[calc(100vw-24px)]",
                                        "bg-white dark:bg-gray-800",
                                        "rounded-xl shadow-xl",
                                        "border border-gray-200 dark:border-gray-700",
                                        "overflow-hidden z-50",
                                        "animate-in fade-in-0 zoom-in-95 slide-in-from-top-2",
                                        "duration-200"
                                    )}
                                    role="menu"
                                    onClick={(e) => e.stopPropagation()}
                                >
                                {/* Tabs */}
                                <div className={cn(
                                    "flex border-b border-gray-200 dark:border-gray-700"
                                )}>
                                    <button
                                        onClick={() => setShareTab('invite')}
                                        className={cn(
                                            "flex-1 px-4 py-3 text-sm font-medium transition-colors",
                                            "border-b-2",
                                            shareTab === 'invite'
                                                ? "border-blue-500 text-blue-600 dark:text-blue-400"
                                                : "border-transparent text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200"
                                        )}
                                    >
                                        Invite
                                    </button>
                                    <button
                                        onClick={() => setShareTab('embed')}
                                        className={cn(
                                            "flex-1 px-4 py-3 text-sm font-medium transition-colors",
                                            "border-b-2",
                                            shareTab === 'embed'
                                                ? "border-blue-500 text-blue-600 dark:text-blue-400"
                                                : "border-transparent text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200"
                                        )}
                                    >
                                        Embed
                                    </button>
                                    <button
                                        onClick={() => setShareTab('publish')}
                                        className={cn(
                                            "flex-1 px-4 py-3 text-sm font-medium transition-colors",
                                            "border-b-2",
                                            shareTab === 'publish'
                                                ? "border-blue-500 text-blue-600 dark:text-blue-400"
                                                : "border-transparent text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200"
                                        )}
                                    >
                                        Publish
                                    </button>
                                </div>

                                {/* Content */}
                                <div className="p-5 max-h-[600px] overflow-y-auto">
                                    {shareTab === 'invite' && (
                                        <div className="space-y-5">
                                            {/* Email/Integration Invite */}
                                            <div>
                                                <div className="relative">
                                                    <UserPlus className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                                                    <input
                                                        type="text"
                                                        placeholder="Enter emails or invite from the team, Slack, Google or Microsoft"
                                                        className={cn(
                                                            "w-full pl-10 pr-3 py-3 rounded-lg border-2 border-blue-500",
                                                            "bg-white dark:bg-gray-800",
                                                            "text-gray-900 dark:text-white",
                                                            "placeholder:text-gray-400 dark:placeholder:text-gray-500",
                                                            "focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                                                        )}
                                                    />
                                                </div>
                                                <div className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                                                    <span className="underline cursor-pointer">team</span>, <span className="underline cursor-pointer">Slack</span>, <span className="underline cursor-pointer">Google</span>, or <span className="underline cursor-pointer">Microsoft</span>
                                                </div>
                                            </div>

                                            {/* Shareable Link */}
                                            <div>
                                                <div className={cn(
                                                    "flex items-center gap-3 p-3 rounded-lg",
                                                    "bg-gray-50 dark:bg-gray-900/50",
                                                    "border border-gray-200 dark:border-gray-700"
                                                )}>
                                                    <Link2 className="w-5 h-5 text-gray-400 shrink-0" />
                                                    <span className="flex-1 text-sm text-gray-600 dark:text-gray-400 truncate">
                                                        https://miro.com/welcomeonl...
                                                    </span>
                                                    <select className={cn(
                                                        "text-xs px-2 py-1 rounded border",
                                                        "bg-white dark:bg-gray-800",
                                                        "border-gray-300 dark:border-gray-600",
                                                        "text-gray-700 dark:text-gray-300"
                                                    )}>
                                                        <option>Can edit</option>
                                                        <option>Can view</option>
                                                        <option>No access</option>
                                                    </select>
                                                    <button className={cn(
                                                        "px-3 py-1.5 rounded-lg text-sm font-medium",
                                                        "bg-primary text-primary-foreground",
                                                        "hover:bg-primary/90 transition-colors"
                                                    )}>
                                                        Copy team invite link
                                                    </button>
                                                </div>
                                            </div>

                                            {/* Board Access */}
                                            <div>
                                                <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                                                    BOARD ACCESS
                                                </div>
                                                <div className="space-y-3">
                                                    {/* Team Access */}
                                                    <div className="flex items-center justify-between">
                                                        <div className="flex items-center gap-3">
                                                            <div className="flex -space-x-2">
                                                                <div className="w-8 h-8 rounded-full bg-purple-500 flex items-center justify-center text-white text-xs font-semibold border-2 border-white dark:border-gray-800">
                                                                    K
                                                                </div>
                                                                <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white text-xs font-semibold border-2 border-white dark:border-gray-800">
                                                                    F
                                                                </div>
                                                                <div className="w-8 h-8 rounded-full bg-green-500 flex items-center justify-center text-white text-xs font-semibold border-2 border-white dark:border-gray-800">
                                                                    L
                                                                </div>
                                                            </div>
                                                            <span className="text-sm text-gray-900 dark:text-white">
                                                                kaique team has access
                                                            </span>
                                                        </div>
                                                        <div className="flex items-center gap-2">
                                                            <ChevronUp className="w-4 h-4 text-gray-400" />
                                                            <button className="text-sm text-blue-500 hover:text-blue-600 dark:text-blue-400">
                                                                Manage access
                                                            </button>
                                                        </div>
                                                    </div>

                                                    {/* Anyone with link */}
                                                    <div className="flex items-center justify-between">
                                                        <div className="flex items-center gap-3">
                                                            <Globe className="w-5 h-5 text-gray-400" />
                                                            <span className="text-sm text-gray-900 dark:text-white">
                                                                Anyone with the link
                                                            </span>
                                                        </div>
                                                        <select className={cn(
                                                            "text-xs px-2 py-1 rounded border",
                                                            "bg-white dark:bg-gray-800",
                                                            "border-gray-300 dark:border-gray-600",
                                                            "text-gray-700 dark:text-gray-300"
                                                        )}>
                                                            <option>No access</option>
                                                            <option>Can view</option>
                                                            <option>Can edit</option>
                                                        </select>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {shareTab === 'embed' && (
                                        <div className="space-y-5">
                                            {/* Info Banner */}
                                            <div className={cn(
                                                "flex items-start gap-3 p-3 rounded-lg",
                                                "bg-blue-50 dark:bg-blue-900/20",
                                                "border border-blue-200 dark:border-blue-800"
                                            )}>
                                                <Lock className="w-5 h-5 text-blue-500 shrink-0 mt-0.5" />
                                                <div className="text-sm text-blue-700 dark:text-blue-300">
                                                    This board is private. Only invited people who are signed in will see it. Change who can see it in the <button className="underline font-medium">invite section</button>.
                                                </div>
                                            </div>

                                            {/* Start view */}
                                            <div>
                                                <label className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 block">
                                                    Start view:
                                                </label>
                                                <select className={cn(
                                                    "w-full px-3 py-2 rounded-lg border",
                                                    "bg-white dark:bg-gray-800",
                                                    "border-gray-300 dark:border-gray-600",
                                                    "text-gray-900 dark:text-white"
                                                )}>
                                                    <option>Board</option>
                                                    <option>Presentation</option>
                                                </select>
                                            </div>

                                            {/* View only checkbox */}
                                            <div className="flex items-center gap-2">
                                                <input
                                                    type="checkbox"
                                                    id="view-only"
                                                    defaultChecked
                                                    className="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
                                                />
                                                <label htmlFor="view-only" className="text-sm text-gray-700 dark:text-gray-300">
                                                    View only
                                                </label>
                                            </div>

                                            {/* Preview */}
                                            <div className={cn(
                                                "w-full h-64 rounded-lg border-2 border-dashed",
                                                "border-gray-300 dark:border-gray-600",
                                                "bg-gray-50 dark:bg-gray-900/50",
                                                "flex items-center justify-center"
                                            )}>
                                                <div className="text-sm text-gray-400 dark:text-gray-500">
                                                    Board preview
                                                </div>
                                            </div>

                                            {/* Embed code */}
                                            <div>
                                                <div className="flex items-center justify-between mb-2">
                                                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                                        Embed code
                                                    </span>
                                                    <button className="text-blue-500 hover:text-blue-600">
                                                        <Code className="w-4 h-4" />
                                                    </button>
                                                </div>
                                                <div className="flex gap-2">
                                                    <button className={cn(
                                                        "flex-1 px-4 py-2 rounded-lg text-sm font-medium",
                                                        "bg-primary text-primary-foreground",
                                                        "hover:bg-primary/90 transition-colors",
                                                        "flex items-center justify-center gap-2"
                                                    )}>
                                                        <Code className="w-4 h-4" />
                                                        Copy code
                                                    </button>
                                                    <button className={cn(
                                                        "flex-1 px-4 py-2 rounded-lg text-sm font-medium",
                                                        "bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300",
                                                        "border border-gray-300 dark:border-gray-600",
                                                        "hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors",
                                                        "flex items-center justify-center gap-2"
                                                    )}>
                                                        <Link2 className="w-4 h-4" />
                                                        Copy link
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {shareTab === 'publish' && (
                                        <div className="space-y-5">
                                            <div className="text-center py-8">
                                                <p className="text-sm text-gray-600 dark:text-gray-400">
                                                    Publish content coming soon...
                                                </p>
                                            </div>
                                        </div>
                                    )}
                                </div>
                                </div>
                            </>
                        )}
                    </div>

                    {/* Dark/Light Mode Toggle */}
                    <button
                        className={cn(
                            "flex items-center justify-center",
                            itemHoverClass,
                            "h-8 w-8 rounded-lg",
                            "focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2",
                            "dark:focus:ring-offset-gray-900"
                        )}
                        onClick={() => {
                            setTheme(currentTheme === 'dark' ? 'light' : 'dark')
                        }}
                        aria-label="Toggle theme"
                        title={currentTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                    >
                        {currentTheme === 'dark' ? (
                            <Sun className={cn(
                                "w-4 h-4",
                                isDark ? "text-white/80" : "text-gray-900"
                            )} />
                        ) : (
                            <Moon className={cn(
                                "w-4 h-4",
                                isDark ? "text-white/80" : "text-gray-900"
                            )} />
                        )}
                    </button>

                    {/* Notifications Bell */}
                    <div className="relative">
                    <button
                        className={cn(
                                "flex items-center justify-center relative",
                            itemHoverClass,
                                "h-8 w-8 rounded-lg",
                                "focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2",
                            "dark:focus:ring-offset-gray-900"
                        )}
                        onClick={(e) => {
                            e.stopPropagation()
                                setShowShareMenu(false)
                                // Close all other menus when opening notifications
                                setShowHelpMenu(false)
                                setShowProfileMenu(false)
                                setShowShareMenu(false)
                                setShowNotifications(!showNotifications)
                        }}
                            aria-label="Notifications"
                            title="Notifications"
                    >
                            <Bell className={cn(
                                "w-4 h-4",
                                isDark ? "text-white/80" : "text-gray-900"
                            )} />
                            {/* Notification badge - optional */}
                            {/* <div className="absolute top-1 right-1 h-2 w-2 rounded-full bg-red-500 border-2 border-white dark:border-gray-800" /> */}
                        </button>
                        
                        {/* Notifications Dropdown */}
                        {showNotifications && (
                            <div
                                className={cn(
                                    "absolute right-0 top-full mt-3 w-80",
                                    "bg-white dark:bg-gray-800",
                                    "rounded-xl shadow-xl",
                                    "border border-gray-200 dark:border-gray-700",
                                    "overflow-hidden z-50",
                                    "animate-in fade-in-0 zoom-in-95 slide-in-from-top-2",
                                    "duration-200",
                                    "max-h-[500px] flex flex-col"
                                )}
                                role="menu"
                                onClick={(e) => e.stopPropagation()}
                            >
                                {/* Header */}
                                <div className={cn(
                                    "px-4 py-3 border-b border-gray-200 dark:border-gray-700",
                                    "flex items-center justify-between"
                                )}>
                                    <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                                        Notifications
                                    </h3>
                                    <button
                                        onClick={() => setShowNotifications(false)}
                                        className="text-xs text-blue-500 hover:text-blue-600 dark:text-blue-400"
                                    >
                                        Mark all as read
                                    </button>
                            </div>
                            
                                {/* Notifications List */}
                                <div className="flex-1 overflow-y-auto">
                                    {/* Empty State */}
                                    <div className="px-4 py-8 text-center">
                                        <Bell className={cn(
                                            "w-12 h-12 mx-auto mb-3",
                                            "text-gray-300 dark:text-gray-600"
                                        )} />
                                        <p className="text-sm text-gray-500 dark:text-gray-400">
                                            No notifications
                                        </p>
                                    </div>

                                    {/* Example Notification Items (commented out - can be uncommented when needed) */}
                                    {/* 
                                <div className={cn(
                                        "px-4 py-3 border-b border-gray-100 dark:border-gray-700",
                                        "hover:bg-gray-50 dark:hover:bg-gray-700/50",
                                        "transition-colors cursor-pointer"
                                )}>
                                        <div className="flex items-start gap-3">
                                            <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white text-xs font-semibold shrink-0">
                                                K
                                </div>
                                            <div className="flex-1 min-w-0">
                                                <p className="text-sm text-gray-900 dark:text-white">
                                                    <span className="font-medium">Kaique</span> shared a board with you
                                                </p>
                                                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                                    2 hours ago
                                                </p>
                            </div>
                        </div>
                                    </div>
                                    */}
                                </div>

                                {/* Footer */}
                                <div className={cn(
                                    "px-4 py-3 border-t border-gray-200 dark:border-gray-700",
                                    "text-center"
                                )}>
                                    <button className="text-sm text-blue-500 hover:text-blue-600 dark:text-blue-400">
                                        View all notifications
                    </button>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Help Button */}
                    <div className="relative">
                        <button
                            className={cn(
                                "flex items-center justify-center",
                                itemHoverClass,
                                "h-8 w-8 rounded-lg",
                                "focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2",
                                "dark:focus:ring-offset-gray-900"
                            )}
                            onClick={(e) => {
                                e.stopPropagation()
                                // Close all other menus when opening help menu
                                setShowNotifications(false)
                                setShowProfileMenu(false)
                                setShowShareMenu(false)
                                setShowHelpMenu(!showHelpMenu)
                            }}
                            aria-label="Help"
                            title="Help"
                        >
                            <HelpCircle className={cn(
                                "w-4 h-4",
                                isDark ? "text-white/80" : "text-gray-900"
                            )} />
                        </button>

                        {/* Help Menu Dropdown */}
                        {showHelpMenu && (
                        <div 
                            className={cn(
                                    "absolute right-0 top-full mt-3 w-56",
                                "bg-white dark:bg-gray-800",
                                "rounded-xl shadow-xl",
                                "border border-gray-200 dark:border-gray-700",
                                "overflow-hidden z-50",
                                "animate-in fade-in-0 zoom-in-95 slide-in-from-top-2",
                                    "duration-200",
                                    "py-1"
                            )}
                            role="menu"
                            onClick={(e) => e.stopPropagation()}
                        >
                                {/* Documentation */}
                                        <button
                                            onClick={() => {
                                        console.log("Open documentation")
                                        setShowHelpMenu(false)
                                            }}
                                            className={cn(
                                        "w-full text-left flex items-center gap-2",
                                        "hover:bg-blue-50 dark:hover:bg-blue-900/20",
                                        "transition-all duration-200 rounded-md",
                                        "text-gray-900 dark:text-white px-4 py-2.5"
                                            )}
                                            role="menuitem"
                                        >
                                    <BookOpen className="w-4 h-4 shrink-0 text-gray-500 dark:text-gray-400" />
                                    <span className="text-sm">Documentation</span>
                                        </button>

                                {/* Tutorials */}
                                        <button
                                            onClick={() => {
                                        console.log("Open tutorials")
                                        setShowHelpMenu(false)
                                            }}
                                            className={cn(
                                        "w-full text-left flex items-center gap-2",
                                        "hover:bg-blue-50 dark:hover:bg-blue-900/20",
                                        "transition-all duration-200 rounded-md",
                                        "text-gray-900 dark:text-white px-4 py-2.5"
                                            )}
                                            role="menuitem"
                                        >
                                    <Video className="w-4 h-4 shrink-0 text-gray-500 dark:text-gray-400" />
                                    <span className="text-sm">Tutorials</span>
                                        </button>

                                {/* Support */}
                                        <button
                                            onClick={() => {
                                        console.log("Open support")
                                        setShowHelpMenu(false)
                                            }}
                                            className={cn(
                                        "w-full text-left flex items-center gap-2",
                                        "hover:bg-blue-50 dark:hover:bg-blue-900/20",
                                        "transition-all duration-200 rounded-md",
                                        "text-gray-900 dark:text-white px-4 py-2.5"
                                            )}
                                            role="menuitem"
                                        >
                                    <MessageCircle className="w-4 h-4 shrink-0 text-gray-500 dark:text-gray-400" />
                                    <span className="text-sm">Support</span>
                                        </button>
                            </div>
                        )}
                                    </div>

                    {/* Profile Button - Replaced Share */}
                    <div className="relative">
                        <button
                            className={cn(
                                "flex items-center justify-center",
                                "h-8 w-8 rounded-full",
                                "text-white text-xs font-semibold",
                                "transition-all duration-200",
                                "focus:outline-none focus:ring-2 focus:ring-yellow-400/30 focus:ring-offset-2",
                                "dark:focus:ring-offset-gray-900",
                                "shadow-sm hover:shadow-md",
                                "relative overflow-hidden",
                                showProfileMenu && "ring-2 ring-yellow-400/30"
                            )}
                            style={{
                                background: `
                                    linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 50%, #1a2f4f 100%),
                                    radial-gradient(1.5px 1.5px at 30% 40%, rgba(255, 255, 0, 0.4), transparent),
                                    radial-gradient(1px 1px at 70% 60%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 50% 20%, rgba(255, 255, 0, 0.35), transparent),
                                    radial-gradient(1px 1px at 20% 80%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 80% 30%, rgba(255, 255, 0, 0.25), transparent)
                                `,
                                backgroundColor: '#1e3a5f'
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = `
                                    linear-gradient(135deg, #2a4a6f 0%, #3d5a7f 50%, #2a3f5f 100%),
                                    radial-gradient(1.5px 1.5px at 30% 40%, rgba(255, 255, 0, 0.4), transparent),
                                    radial-gradient(1px 1px at 70% 60%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 50% 20%, rgba(255, 255, 0, 0.35), transparent),
                                    radial-gradient(1px 1px at 20% 80%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 80% 30%, rgba(255, 255, 0, 0.25), transparent)
                                `
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = `
                                    linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 50%, #1a2f4f 100%),
                                    radial-gradient(1.5px 1.5px at 30% 40%, rgba(255, 255, 0, 0.4), transparent),
                                    radial-gradient(1px 1px at 70% 60%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 50% 20%, rgba(255, 255, 0, 0.35), transparent),
                                    radial-gradient(1px 1px at 20% 80%, rgba(255, 255, 0, 0.3), transparent),
                                    radial-gradient(1.5px 1.5px at 80% 30%, rgba(255, 255, 0, 0.25), transparent)
                                `
                            }}
                            onClick={(e) => {
                                e.stopPropagation()
                                // Close all other menus when opening profile menu
                                setShowNotifications(false)
                                setShowShareMenu(false)
                                setShowHelpMenu(false)
                                setShowProfileMenu(!showProfileMenu)
                            }}
                            aria-label="Profile"
                            title="Profile"
                        >
                            {userInitials}
                        </button>

                        {/* Profile Dropdown */}
                        <ProfileDropdown
                            isOpen={showProfileMenu}
                            onOpenChange={setShowProfileMenu}
                        />
                    </div>
                </div>
            </div>

            {/* Backdrop for closing menus */}
            {(showShareMenu || showProfileMenu || showNotifications || showHelpMenu) && !showSpacesMenu && !showStarredMenu && !showRecentMenu && !showCrewsMenu && (
                <div
                    className="fixed inset-0 z-40"
                    onClick={() => {
                        setShowShareMenu(false)
                        setShowProfileMenu(false)
                        setShowNotifications(false)
                        setShowHelpMenu(false)
                        setShowSpacesMenu(false)
                        setShowStarredMenu(false)
                        setShowRecentMenu(false)
                        setShowCrewsMenu(false)
                    }}
                    aria-hidden="true"
                />
            )}

            {/* Create Planet Dialog */}
            <CreatePlanetDialog 
                open={showCreatePlanetDialog}
                onOpenChange={setShowCreatePlanetDialog}
            />
        </>
    )
}
