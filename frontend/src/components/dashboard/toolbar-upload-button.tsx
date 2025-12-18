"use client"

import { useRef } from "react"
import { Image } from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"

interface ToolbarUploadButtonProps {
    onUpload: (files: FileList) => void
    accept?: string
    multiple?: boolean
    disabled?: boolean
}

export function ToolbarUploadButton({ 
    onUpload, 
    accept = ".csv,.xlsx,.xls,.png,.jpg,.jpeg,.pdf",
    multiple = true,
    disabled = false
}: ToolbarUploadButtonProps) {
    const fileInputRef = useRef<HTMLInputElement>(null)
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'

    const handleClick = () => {
        if (!disabled) {
        fileInputRef.current?.click()
        }
    }

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files
        if (files && files.length > 0) {
            onUpload(files)
        }
        // Reset input to allow selecting the same file again
        if (fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }

    return (
        <>
            <input
                ref={fileInputRef}
                type="file"
                accept={accept}
                multiple={multiple}
                onChange={handleFileChange}
                className="hidden"
            />
            <button
                onClick={handleClick}
                disabled={disabled}
                className={cn(
                    "h-9 w-9 rounded-lg transition-all duration-200",
                    "flex items-center justify-center",
                    disabled
                        ? "opacity-50 cursor-not-allowed"
                        : "hover:bg-accent active:scale-95",
                    isDark
                        ? "text-white/90 hover:bg-white/8 active:bg-white/12"
                        : "text-gray-900 hover:bg-black/5 active:bg-black/10"
                )}
                aria-label="Upload files"
            >
                <Image className="w-4.5 h-4.5" />
            </button>
        </>
    )
}

