"use client"

import { motion, AnimatePresence } from "framer-motion"
import { User, LogOut } from "lucide-react"
import { useRouter } from "next/navigation"
import { useUserStore } from "@/store/user-store"
import { cn } from "@/lib/utils"

interface ProfileDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
}

export function ProfileDropdown({ isOpen, onOpenChange, onClose }: ProfileDropdownProps) {
  const router = useRouter()
  const { logout, user } = useUserStore()

  const handleLogout = async () => {
    await logout()
    onOpenChange(false)
    onClose?.()
    router.push("/login")
  }

  const handleProfile = () => {
    onOpenChange(false)
    onClose?.()
    router.push("/dashboard/settings")
  }

  if (!isOpen) return null

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.2 }}
          className={cn(
            "absolute right-0 top-full mt-3 w-64",
            "bg-white dark:bg-gray-900",
            "rounded-xl shadow-xl",
            "border border-gray-200 dark:border-gray-800",
            "overflow-hidden z-[60]",
            "pointer-events-auto"
          )}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="p-3 space-y-1">
            <button
              onClick={handleProfile}
              className={cn(
                "w-full text-left px-3 py-2 rounded-lg",
                "hover:bg-gray-100 dark:hover:bg-gray-800",
                "transition-all duration-200",
                "flex items-center gap-2"
              )}
            >
              <User className="w-4 h-4 text-gray-500 dark:text-gray-400" />
              <span className="text-sm text-gray-700 dark:text-gray-300">Profile</span>
            </button>
            
            <div className="h-px my-1 bg-gray-200 dark:bg-gray-700" />
            
            <button
              onClick={handleLogout}
              className={cn(
                "w-full text-left px-3 py-2 rounded-lg",
                "hover:bg-red-50 dark:hover:bg-red-900/20",
                "transition-all duration-200",
                "flex items-center gap-2",
                "text-red-600 dark:text-red-400"
              )}
            >
              <LogOut className="w-4 h-4" />
              <span className="text-sm">Logout</span>
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

