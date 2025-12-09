"use client"

import { useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion } from "framer-motion"
import {
    LayoutDashboard,
    FolderKanban,
    Link2,
    Settings,
    HelpCircle,
    ChevronLeft,
    Menu,
    Bot
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

const NAV_ITEMS = [
    { icon: LayoutDashboard, label: "Dashboard", href: "/dashboard" },
    { icon: FolderKanban, label: "Projects", href: "/dashboard/projects" },
    { icon: Link2, label: "Connections", href: "/dashboard/connections" },
    { icon: Bot, label: "AI History", href: "/dashboard/ai-history" },
    { icon: Settings, label: "Settings", href: "/dashboard/settings" },
]

export function Sidebar() {
    const [collapsed, setCollapsed] = useState(false)
    const pathname = usePathname()

    return (
        <motion.div
            className={cn(
                "h-screen border-r bg-card/50 backdrop-blur-xl flex flex-col transition-all duration-300 z-50",
                collapsed ? "w-16" : "w-64"
            )}
            initial={false}
            animate={{ width: collapsed ? 64 : 256 }}
        >
            <div className="p-4 flex items-center justify-between border-b">
                {!collapsed && (
                    <motion.span
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="font-bold text-xl bg-gradient-to-r from-primary to-purple-600 bg-clip-text text-transparent truncate"
                    >
                        AI Nexus
                    </motion.span>
                )}
                <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setCollapsed(!collapsed)}
                    className="ml-auto"
                >
                    {collapsed ? <Menu className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
                </Button>
            </div>

            <div className="flex-1 py-4 flex flex-col gap-2 px-2">
                <TooltipProvider delayDuration={0}>
                    {NAV_ITEMS.map((item) => (
                        <Tooltip key={item.href}>
                            <TooltipTrigger asChild>
                                <Link href={item.href}>
                                    <Button
                                        variant={pathname === item.href ? "secondary" : "ghost"}
                                        className={cn(
                                            "w-full justify-start",
                                            collapsed ? "justify-center px-2" : "px-4"
                                        )}
                                    >
                                        <item.icon className={cn("w-5 h-5", collapsed ? "mr-0" : "mr-2")} />
                                        {!collapsed && <span>{item.label}</span>}
                                    </Button>
                                </Link>
                            </TooltipTrigger>
                            {collapsed && <TooltipContent side="right">{item.label}</TooltipContent>}
                        </Tooltip>
                    ))}
                </TooltipProvider>
            </div>

            <div className="p-4 border-t">
                <Button variant="ghost" className={cn("w-full justify-start", collapsed ? "justify-center px-2" : "px-4")}>
                    <HelpCircle className={cn("w-5 h-5", collapsed ? "mr-0" : "mr-2")} />
                    {!collapsed && <span>Help & Support</span>}
                </Button>
            </div>
        </motion.div>
    )
}
